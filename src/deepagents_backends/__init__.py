"""
Deep Agents Remote Backends

S3 and PostgreSQL backend implementations for LangChain's Deep Agents.
Supports any S3-compatible storage (AWS S3, MinIO, etc.) and PostgreSQL
with connection pooling for optimal performance.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, AsyncIterator, Coroutine

import aioboto3
import psycopg_pool
import wcmatch.glob as wcglob
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from deepagents.backends.utils import (
    check_empty_content,
    format_content_with_line_numbers,
    perform_string_replacement,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

__all__ = ["S3Backend", "S3Config", "PostgresBackend", "PostgresConfig"]


class _AsyncThread(threading.Thread):
    """helper thread class for running async coroutines in a separate thread"""

    def __init__(self, coroutine: Coroutine[Any, Any, Any]):
        self.coroutine = coroutine
        self.result = None
        self.exception = None

        super().__init__(daemon=True)

    def run(self):
        try:
            self.result = asyncio.run(self.coroutine)
        except Exception as e:
            self.exception = e


def run_async_safely[T](coroutine: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """safely runs a coroutine with handling of an existing event loop.

    This function detects if there's already a running event loop and uses
    a separate thread if needed to avoid the "asyncio.run() cannot be called
    from a running event loop" error. This is particularly useful in environments
    like Jupyter notebooks, FastAPI applications, or other async frameworks.

    Args:
        coroutine: The coroutine to run
        timeout: max seconds to wait for. None means hanging forever

    Returns:
        The result of the coroutine

    Raises:
        Any exception raised by the coroutine
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # There's a running loop, use a separate thread
        thread = _AsyncThread(coroutine)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError("The operation timed out after %f seconds" % timeout)

        if thread.exception:
            raise thread.exception

        return thread.result
    else:
        if timeout:
            coroutine = asyncio.wait_for(coroutine, timeout)

        return asyncio.run(coroutine)


# =============================================================================
# S3 Backend (S3-compatible: AWS S3, MinIO, etc.)
# =============================================================================


@dataclass
class S3Config:
    """Configuration for S3-compatible storage."""

    bucket: str
    prefix: str = ""
    region: str = "us-east-1"
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    use_ssl: bool = True
    max_pool_connections: int = 50
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3


class S3Backend(BackendProtocol):
    """
    S3-compatible backend for Deep Agents file operations.

    Supports AWS S3, MinIO, and any S3-compatible object storage.
    All operations are async-native using aioboto3.

    Files are stored as objects with paths mapping to S3 keys.
    Content is stored as JSON with the structure:
    {"content": [...lines], "created_at": "...", "modified_at": "..."}
    """

    def __init__(self, config: S3Config) -> None:
        self._config = config
        self._prefix = config.prefix.strip("/")
        if self._prefix:
            self._prefix += "/"

        self._boto_config = BotoConfig(
            region_name=config.region,
            signature_version="s3v4",
            retries={"max_attempts": config.max_retries, "mode": "adaptive"},
            max_pool_connections=config.max_pool_connections,
            connect_timeout=config.connect_timeout,
            read_timeout=config.read_timeout,
        )

        session_kwargs: dict[str, Any] = {}
        if config.access_key_id:
            session_kwargs["aws_access_key_id"] = config.access_key_id
        if config.secret_access_key:
            session_kwargs["aws_secret_access_key"] = config.secret_access_key

        self._session = aioboto3.Session(**session_kwargs)
        self._bucket = config.bucket

    def _s3_key(self, path: str) -> str:
        """Convert virtual path to S3 key."""
        clean = path.lstrip("/")
        return f"{self._prefix}{clean}"

    def _virtual_path(self, key: str) -> str:
        """Convert S3 key to virtual path."""
        if self._prefix and key.startswith(self._prefix):
            key = key[len(self._prefix) :]
        return "/" + key.lstrip("/")

    @asynccontextmanager
    async def _client(self) -> AsyncIterator["S3Client"]:
        """Get S3 client context."""
        async with self._session.client(
            "s3",
            config=self._boto_config,
            endpoint_url=self._config.endpoint_url,
            use_ssl=self._config.use_ssl,
        ) as client:
            yield client

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        """Get file data dict from S3."""
        key = self._s3_key(path)
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                async with response["Body"] as stream:
                    content = await stream.read()
                return json.loads(content.decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    async def _put_file_data(
        self, path: str, data: dict[str, Any], *, update_modified: bool = True
    ) -> None:
        """Put file data dict to S3."""
        key = self._s3_key(path)
        if update_modified:
            data["modified_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(data).encode("utf-8")
        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType="application/json",
            )

    async def _exists(self, path: str) -> bool:
        """Check if file exists in S3."""
        key = self._s3_key(path)
        try:
            async with self._client() as client:
                await client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    async def _list_keys(self, prefix: str = "") -> list[dict[str, Any]]:
        """List all keys with a prefix."""
        full_prefix = self._s3_key(prefix)
        results: list[dict[str, Any]] = []
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self._bucket, Prefix=full_prefix
            ):
                for obj in page.get("Contents", []):
                    results.append(obj)
        return results

    # -------------------------------------------------------------------------
    # BackendProtocol Implementation
    # -------------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        """Sync wrapper for als_info."""
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        """List files in a directory."""
        prefix = path.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        objects = await self._list_keys(prefix)
        results: list[FileInfo] = []
        seen_dirs: set[str] = set()

        for obj in objects:
            key = obj["Key"]
            vpath = self._virtual_path(key)

            # Check if this is a direct child or nested
            rel = vpath[len("/" + prefix) :] if prefix else vpath[1:]
            if "/" in rel:
                # This is in a subdirectory, add the directory entry
                dir_name = rel.split("/")[0]
                dir_path = "/" + prefix + dir_name + "/"
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    results.append({"path": dir_path, "is_dir": True})
            else:
                # Direct file
                results.append(
                    {
                        "path": vpath,
                        "is_dir": False,
                        "size": obj.get("Size", 0),
                        "modified_at": obj["LastModified"].isoformat()
                        if "LastModified" in obj
                        else None,
                    }
                )

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Sync wrapper for aread."""
        return run_async_safely(
            self.aread(file_path, offset, limit)
        )

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers."""
        data = await self._get_file_data(file_path)
        if data is None:
            return f"Error: File '{file_path}' not found"

        lines = data.get("content", [])
        if not lines:
            empty_msg = check_empty_content("")
            if empty_msg:
                return empty_msg

        if offset >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

        selected = lines[offset : offset + limit]
        return format_content_with_line_numbers(selected, start_line=offset + 1)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Sync wrapper for awrite."""
        return run_async_safely(
            self.awrite(file_path, content)
        )

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Create a new file."""
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "content": content.splitlines(),
            "created_at": now,
            "modified_at": now,
        }
        try:
            await self._put_file_data(file_path, data, update_modified=False)
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Sync wrapper for aedit."""
        return run_async_safely(
            self.aedit(file_path, old_string, new_string, replace_all)
        )

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing strings."""
        data = await self._get_file_data(file_path)
        if data is None:
            return EditResult(error=f"Error: File '{file_path}' not found")

        content = "\n".join(data.get("content", []))
        result = perform_string_replacement(content, old_string, new_string, replace_all)

        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result
        data["content"] = new_content.splitlines()

        try:
            await self._put_file_data(file_path, data)
            return EditResult(
                path=file_path, files_update=None, occurrences=int(occurrences)
            )
        except Exception as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """Sync wrapper for agrep_raw."""
        return run_async_safely(
            self.agrep_raw(pattern, path, glob)
        )

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """Search for pattern in files."""
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        search_prefix = (path or "/").lstrip("/")
        objects = await self._list_keys(search_prefix)
        matches: list[GrepMatch] = []

        for obj in objects:
            vpath = self._virtual_path(obj["Key"])
            filename = PurePosixPath(vpath).name

            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue

            data = await self._get_file_data(vpath)
            if data is None:
                continue

            for line_num, line in enumerate(data.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": vpath, "line": line_num, "text": line})

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Sync wrapper for aglob_info."""
        return run_async_safely(
            self.aglob_info(pattern, path)
        )

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        search_prefix = path.lstrip("/")
        objects = await self._list_keys(search_prefix)
        results: list[FileInfo] = []

        for obj in objects:
            vpath = self._virtual_path(obj["Key"])
            rel_path = vpath[len(path) :].lstrip("/") if path != "/" else vpath[1:]

            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(vpath, pattern):
                results.append(
                    {
                        "path": vpath,
                        "is_dir": False,
                        "size": obj.get("Size", 0),
                        "modified_at": obj["LastModified"].isoformat()
                        if "LastModified" in obj
                        else None,
                    }
                )

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Sync wrapper for aupload_files."""
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """Upload multiple files."""
        responses: list[FileUploadResponse] = []
        async with self._client() as client:
            for path, content in files:
                try:
                    key = self._s3_key(path)
                    await client.put_object(
                        Bucket=self._bucket, Key=key, Body=content
                    )
                    responses.append(FileUploadResponse(path=path, error=None))
                except ClientError as e:
                    code = e.response["Error"]["Code"]
                    if code == "AccessDenied":
                        responses.append(
                            FileUploadResponse(path=path, error="permission_denied")
                        )
                    else:
                        responses.append(
                            FileUploadResponse(path=path, error="invalid_path")
                        )
                except Exception:
                    responses.append(
                        FileUploadResponse(path=path, error="invalid_path")
                    )
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Sync wrapper for adownload_files."""
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files."""
        responses: list[FileDownloadResponse] = []
        async with self._client() as client:
            for path in paths:
                try:
                    key = self._s3_key(path)
                    response = await client.get_object(Bucket=self._bucket, Key=key)
                    async with response["Body"] as stream:
                        content = await stream.read()
                    responses.append(
                        FileDownloadResponse(path=path, content=content, error=None)
                    )
                except ClientError as e:
                    code = e.response["Error"]["Code"]
                    if code == "NoSuchKey":
                        responses.append(
                            FileDownloadResponse(
                                path=path, content=None, error="file_not_found"
                            )
                        )
                    elif code == "AccessDenied":
                        responses.append(
                            FileDownloadResponse(
                                path=path, content=None, error="permission_denied"
                            )
                        )
                    else:
                        responses.append(
                            FileDownloadResponse(
                                path=path, content=None, error="invalid_path"
                            )
                        )
        return responses


# =============================================================================
# PostgreSQL Backend with Connection Pooling
# =============================================================================


@dataclass
class PostgresConfig:
    """Configuration for PostgreSQL backend."""

    host: str = "localhost"
    port: int = 5432
    database: str = "deepagents"
    user: str = "postgres"
    password: str = ""
    table: str = "files"
    schema: str = "public"
    min_pool_size: int = 5
    max_pool_size: int = 20
    max_idle_seconds: float = 300.0
    connection_timeout: float = 30.0
    sslmode: str = "prefer"

    @property
    def conninfo(self) -> str:
        """Build connection string."""
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password} sslmode={self.sslmode}"
        )


class PostgresBackend(BackendProtocol):
    """
    PostgreSQL backend for Deep Agents file operations.

    Uses psycopg3 with connection pooling for high-performance async operations.
    Files are stored in a table with path as primary key and content as JSONB.

    Table schema:
        path TEXT PRIMARY KEY,
        content JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        modified_at TIMESTAMPTZ NOT NULL
    """

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._table = f"{config.schema}.{config.table}"
        self._pool: psycopg_pool.AsyncConnectionPool | None = None
        self._initialized = False

    def _storage_path(self, path: str) -> str:
        """Convert virtual path to storage path (strip leading /)."""
        return path.lstrip("/")

    def _virtual_path(self, path: str) -> str:
        """Convert storage path to virtual path (add leading /)."""
        return "/" + path.lstrip("/")

    async def _ensure_pool(self) -> psycopg_pool.AsyncConnectionPool:
        """Lazily initialize the connection pool."""
        if self._pool is None:
            self._pool = psycopg_pool.AsyncConnectionPool(
                conninfo=self._config.conninfo,
                min_size=self._config.min_pool_size,
                max_size=self._config.max_pool_size,
                max_idle=self._config.max_idle_seconds,
                timeout=self._config.connection_timeout,
                open=False,
            )
            await self._pool.open()
        return self._pool

    async def initialize(self) -> None:
        """Create table if not exists. Call once on startup."""
        if self._initialized:
            return

        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    path TEXT PRIMARY KEY,
                    content JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._config.table}_path_prefix
                ON {self._table} (path text_pattern_ops)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._config.table}_modified
                ON {self._table} (modified_at DESC)
            """)
            await conn.commit()
        self._initialized = True

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        """Get file data from database."""
        storage_path = self._storage_path(path)
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT content, created_at, modified_at FROM {self._table} WHERE path = %s",
                    (storage_path,),
                )
                row = await cur.fetchone()
                if row:
                    data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    data["created_at"] = row[1].isoformat() if row[1] else None
                    data["modified_at"] = row[2].isoformat() if row[2] else None
                    return data
                return None

    async def _put_file_data(self, path: str, data: dict[str, Any]) -> None:
        """Upsert file data to database."""
        storage_path = self._storage_path(path)
        pool = await self._ensure_pool()
        content_json = json.dumps({"content": data.get("content", [])})
        async with pool.connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._table} (path, content, created_at, modified_at)
                VALUES (%s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (path) DO UPDATE SET
                    content = EXCLUDED.content,
                    modified_at = NOW()
                """,
                (storage_path, content_json),
            )
            await conn.commit()

    async def _exists(self, path: str) -> bool:
        """Check if file exists."""
        storage_path = self._storage_path(path)
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT 1 FROM {self._table} WHERE path = %s", (storage_path,)
                )
                return await cur.fetchone() is not None

    async def _list_paths(self, prefix: str = "/") -> list[tuple[str, datetime, int]]:
        """List all paths with a prefix, returning (virtual_path, modified_at, size)."""
        pool = await self._ensure_pool()
        # Convert virtual prefix to storage prefix
        storage_prefix = self._storage_path(prefix)
        like_pattern = storage_prefix + "%" if storage_prefix else "%"
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT path, modified_at, 
                           COALESCE(jsonb_array_length(content->'content'), 0) as line_count
                    FROM {self._table} 
                    WHERE path LIKE %s
                    ORDER BY path
                    """,
                    (like_pattern,),
                )
                # Return virtual paths
                return [(self._virtual_path(row[0]), row[1], row[2]) for row in await cur.fetchall()]

    # -------------------------------------------------------------------------
    # BackendProtocol Implementation
    # -------------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        """Sync wrapper for als_info."""
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        """List files in a directory."""
        prefix = path if path.endswith("/") or path == "/" else path + "/"
        rows = await self._list_paths(prefix)

        results: list[FileInfo] = []
        seen_dirs: set[str] = set()

        for file_path, modified_at, line_count in rows:
            rel = file_path[len(prefix) :] if prefix != "/" else file_path[1:]

            if "/" in rel:
                dir_name = rel.split("/")[0]
                dir_path = prefix + dir_name + "/"
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    results.append({"path": dir_path, "is_dir": True})
            else:
                results.append(
                    {
                        "path": file_path,
                        "is_dir": False,
                        "size": line_count,
                        "modified_at": modified_at.isoformat() if modified_at else None,
                    }
                )

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Sync wrapper for aread."""
        return run_async_safely(
            self.aread(file_path, offset, limit)
        )

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers."""
        data = await self._get_file_data(file_path)
        if data is None:
            return f"Error: File '{file_path}' not found"

        lines = data.get("content", [])
        if not lines:
            empty_msg = check_empty_content("")
            if empty_msg:
                return empty_msg

        if offset >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

        selected = lines[offset : offset + limit]
        return format_content_with_line_numbers(selected, start_line=offset + 1)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Sync wrapper for awrite."""
        return run_async_safely(
            self.awrite(file_path, content)
        )

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Create a new file."""
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        data = {"content": content.splitlines()}
        try:
            await self._put_file_data(file_path, data)
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Sync wrapper for aedit."""
        return run_async_safely(
            self.aedit(file_path, old_string, new_string, replace_all)
        )

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing strings."""
        data = await self._get_file_data(file_path)
        if data is None:
            return EditResult(error=f"Error: File '{file_path}' not found")

        content = "\n".join(data.get("content", []))
        result = perform_string_replacement(content, old_string, new_string, replace_all)

        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result
        data["content"] = new_content.splitlines()

        try:
            await self._put_file_data(file_path, data)
            return EditResult(
                path=file_path, files_update=None, occurrences=int(occurrences)
            )
        except Exception as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """Sync wrapper for agrep_raw."""
        return run_async_safely(
            self.agrep_raw(pattern, path, glob)
        )

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """Search for pattern in files using PostgreSQL."""
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        search_prefix = path or "/"
        rows = await self._list_paths(search_prefix)
        matches: list[GrepMatch] = []

        for file_path, _, _ in rows:
            filename = PurePosixPath(file_path).name
            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue

            data = await self._get_file_data(file_path)
            if data is None:
                continue

            for line_num, line in enumerate(data.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": file_path, "line": line_num, "text": line})

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Sync wrapper for aglob_info."""
        return run_async_safely(
            self.aglob_info(pattern, path)
        )

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        rows = await self._list_paths(path)
        results: list[FileInfo] = []

        for file_path, modified_at, line_count in rows:
            rel_path = file_path[len(path) :].lstrip("/") if path != "/" else file_path[1:]

            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(file_path, pattern):
                results.append(
                    {
                        "path": file_path,
                        "is_dir": False,
                        "size": line_count,
                        "modified_at": modified_at.isoformat() if modified_at else None,
                    }
                )

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Sync wrapper for aupload_files."""
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """Upload multiple files."""
        responses: list[FileUploadResponse] = []
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            for path, content in files:
                try:
                    content_json = json.dumps(
                        {"content": content.decode("utf-8", errors="replace").splitlines()}
                    )
                    await conn.execute(
                        f"""
                        INSERT INTO {self._table} (path, content, created_at, modified_at)
                        VALUES (%s, %s::jsonb, NOW(), NOW())
                        ON CONFLICT (path) DO UPDATE SET
                            content = EXCLUDED.content,
                            modified_at = NOW()
                        """,
                        (path, content_json),
                    )
                    responses.append(FileUploadResponse(path=path, error=None))
                except Exception:
                    responses.append(FileUploadResponse(path=path, error="invalid_path"))
            await conn.commit()

        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Sync wrapper for adownload_files."""
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files."""
        responses: list[FileDownloadResponse] = []
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            for path in paths:
                try:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            f"SELECT content FROM {self._table} WHERE path = %s",
                            (path,),
                        )
                        row = await cur.fetchone()
                        if row:
                            data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                            content = "\n".join(data.get("content", [])).encode("utf-8")
                            responses.append(
                                FileDownloadResponse(path=path, content=content, error=None)
                            )
                        else:
                            responses.append(
                                FileDownloadResponse(
                                    path=path, content=None, error="file_not_found"
                                )
                            )
                except Exception:
                    responses.append(
                        FileDownloadResponse(path=path, content=None, error="invalid_path")
                    )

        return responses
