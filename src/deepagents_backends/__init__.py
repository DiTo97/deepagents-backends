"""
Deep Agents Remote Backends.

Remote storage backends for Deep Agents across S3, PostgreSQL, Azure Blob,
GCS, MongoDB, and Redis/Valkey.
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
import redis.asyncio as redis
import wcmatch.glob as wcglob
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient
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
from gcloud.aio.storage import Storage as GCSStorage
from motor.motor_asyncio import AsyncIOMotorClient

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

__all__ = [
    "S3Backend",
    "S3Config",
    "PostgresBackend",
    "PostgresConfig",
    "AzureBlobBackend",
    "AzureBlobConfig",
    "GCSBackend",
    "GCSConfig",
    "MongoDBBackend",
    "MongoDBConfig",
    "RedisBackend",
    "RedisConfig",
]


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


def _utcnow_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _make_text_file_data(content: str) -> dict[str, Any]:
    """Build the canonical JSON payload used by text-oriented backends."""
    now = _utcnow_iso()
    return {
        "content": content.splitlines(),
        "created_at": now,
        "modified_at": now,
    }


def _read_text_payload(
    file_path: str,
    data: dict[str, Any] | None,
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Render stored line-array content using Deep Agents' read format."""
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


def _edit_text_payload(
    data: dict[str, Any] | None,
    *,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> tuple[dict[str, Any] | None, int | None, str | None]:
    """Apply Deep Agents string replacement semantics to stored file data."""
    if data is None:
        return None, None, "file_not_found"

    content = "\n".join(data.get("content", []))
    result = perform_string_replacement(content, old_string, new_string, replace_all)
    if isinstance(result, str):
        return None, None, result

    new_content, occurrences = result
    data["content"] = new_content.splitlines()
    return data, int(occurrences), None


def _normalize_virtual_path(path: str) -> str:
    """Normalize any path into a slash-prefixed virtual path."""
    return "/" + path.lstrip("/")


def _build_direct_listing(
    directory_path: str,
    files: list[tuple[str, int | None, str | None]],
) -> list[FileInfo]:
    """Collapse recursive file metadata into direct child file/dir entries."""
    normalized_dir = "/" if directory_path == "/" else "/" + directory_path.strip("/")
    base = normalized_dir.strip("/")
    prefix = f"{base}/" if base else ""

    direct_files: list[FileInfo] = []
    direct_dirs: set[str] = set()

    for virtual_path, size, modified_at in files:
        clean = virtual_path.lstrip("/")
        if prefix:
            if not clean.startswith(prefix):
                continue
            rel = clean[len(prefix) :]
        else:
            rel = clean

        if not rel:
            continue

        child, sep, _rest = rel.partition("/")
        if sep:
            direct_dirs.add(child)
            continue

        direct_files.append(
            {
                "path": _normalize_virtual_path(clean),
                "is_dir": False,
                "size": size or 0,
                "modified_at": modified_at,
            }
        )

    results = direct_files + [
        {
            "path": (
                f"{normalized_dir.rstrip('/')}/{dir_name}/"
                if normalized_dir != "/"
                else f"/{dir_name}/"
            ),
            "is_dir": True,
        }
        for dir_name in sorted(direct_dirs)
    ]
    results.sort(key=lambda item: item.get("path", ""))
    return results


def _matches_glob(pattern: str, path: str, virtual_path: str) -> bool:
    """Return whether a path matches a glob relative to a search root or absolutely."""
    rel_path = (
        virtual_path[len(path) :].lstrip("/") if path != "/" else virtual_path[1:]
    )
    return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(virtual_path, pattern)


def _status_code_from_error(error: Exception) -> int | None:
    """Extract an HTTP-like status code from client exceptions when available."""
    return getattr(error, "status", getattr(error, "code", None))


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
        """List direct children of a directory.

        Uses the S3 ``Delimiter='/'`` parameter so that:

        * ``Contents`` returns only objects *directly* under the prefix
          (no recursive descent into sub-prefixes).
        * ``CommonPrefixes`` returns the virtual sub-directory entries.

        This avoids scanning the full subtree just to derive immediate
        children.
        """
        prefix = path.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        full_prefix = self._s3_key(prefix)
        results: list[FileInfo] = []

        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self._bucket, Prefix=full_prefix, Delimiter="/"
            ):
                for obj in page.get("Contents", []):
                    vpath = self._virtual_path(obj["Key"])
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
                for cp in page.get("CommonPrefixes", []):
                    vpath = self._virtual_path(cp["Prefix"])
                    results.append({"path": vpath, "is_dir": True})

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
        """Search for pattern in files.

        Applies filename (glob) filtering immediately after listing — before
        any object GET — and reuses a single S3 client session for both the
        listing and all subsequent content fetches, eliminating N separate
        session setups.
        """
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        search_prefix = (path or "/").lstrip("/")
        full_prefix = self._s3_key(search_prefix)
        matches: list[GrepMatch] = []

        async with self._client() as client:
            # ── Step 1: list candidate objects ───────────────────────────
            paginator = client.get_paginator("list_objects_v2")
            candidates: list[tuple[str, str]] = []  # (s3_key, virtual_path)
            async for page in paginator.paginate(
                Bucket=self._bucket, Prefix=full_prefix
            ):
                for obj in page.get("Contents", []):
                    vpath = self._virtual_path(obj["Key"])
                    filename = PurePosixPath(vpath).name
                    if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                        continue
                    candidates.append((obj["Key"], vpath))

            # ── Step 2: fetch content — shared session, no per-file setup ─
            for key, vpath in candidates:
                try:
                    response = await client.get_object(Bucket=self._bucket, Key=key)
                    async with response["Body"] as stream:
                        raw = await stream.read()
                    data = json.loads(raw.decode("utf-8"))
                except ClientError as e:
                    if e.response["Error"]["Code"] == "NoSuchKey":
                        continue
                    raise

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
        """Find files matching a glob pattern.

        Extracts the longest literal prefix from *pattern* (the part before
        the first wildcard character) and combines it with *path* to narrow
        the S3 key scan before applying fnmatch.  This avoids listing the
        full keyspace for patterns like ``"models/v2*.json"`` or ``"src/**"``.
        """
        base_prefix = path.lstrip("/")
        if base_prefix and not base_prefix.endswith("/"):
            base_prefix += "/"

        # Longest wildcard-free prefix of the pattern.
        literal: str = ""
        for c in pattern:
            if c in "*?[{":
                break
            literal += c

        effective_prefix = base_prefix + literal
        objects = await self._list_keys(effective_prefix)
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

    # -------------------------------------------------------------------------
    # BackendProtocol Implementation
    # -------------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        """Sync wrapper for als_info."""
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        """List direct children of a directory.

        Uses two SQL queries instead of loading the full descendant set:

        1. A direct-file query that excludes any path containing an extra
           ``/`` after the prefix (``NOT LIKE prefix + '%/%'``).
        2. A distinct-subdirectory query that extracts the first path segment
           of nested descendants via ``SPLIT_PART`` / ``SUBSTR``.

        This avoids materialising the whole subtree just to derive immediate
        children.
        """
        prefix = path if path.endswith("/") or path == "/" else path + "/"
        storage_prefix = self._storage_path(prefix)

        # LIKE patterns.  When storage_prefix is empty (root listing) we use
        # bare wildcards so we don't accidentally prepend a literal "%".
        like_all = (storage_prefix + "%") if storage_prefix else "%"
        like_nested = (storage_prefix + "%/%") if storage_prefix else "%/%"

        # SUBSTR start position (1-based): skip past storage_prefix so that
        # SPLIT_PART returns only the first path segment *after* the prefix.
        substr_start = len(storage_prefix) + 1

        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # ── Direct file children ──────────────────────────────────
                await cur.execute(
                    f"""
                    SELECT path, modified_at,
                           COALESCE(jsonb_array_length(content->'content'), 0)
                    FROM {self._table}
                    WHERE path LIKE %s AND path NOT LIKE %s
                    ORDER BY path
                    """,
                    (like_all, like_nested),
                )
                file_rows = await cur.fetchall()

                # ── Direct subdirectory names ─────────────────────────────
                await cur.execute(
                    f"""
                    SELECT DISTINCT SPLIT_PART(SUBSTR(path, %s), '/', 1)
                    FROM {self._table}
                    WHERE path LIKE %s
                    ORDER BY 1
                    """,
                    (substr_start, like_nested),
                )
                dir_rows = await cur.fetchall()

        results: list[FileInfo] = []
        for row in file_rows:
            results.append(
                {
                    "path": self._virtual_path(row[0]),
                    "is_dir": False,
                    "size": row[2],
                    "modified_at": row[1].isoformat() if row[1] else None,
                }
            )
        for (dir_name,) in dir_rows:
            results.append(
                {
                    "path": self._virtual_path(storage_prefix + dir_name + "/"),
                    "is_dir": True,
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
        """Search for pattern in files using PostgreSQL.

        Fetches all candidate paths and their content in a single SQL query,
        eliminating the previous per-file ``_get_file_data`` loop.
        Glob and regex filtering are applied in Python after the batch fetch.
        """
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        search_prefix = path or "/"
        storage_prefix = self._storage_path(search_prefix)
        like_pattern = storage_prefix + "%" if storage_prefix else "%"

        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT path, content->'content'
                    FROM {self._table}
                    WHERE path LIKE %s
                    ORDER BY path
                    """,
                    (like_pattern,),
                )
                rows = await cur.fetchall()

        matches: list[GrepMatch] = []
        for storage_path, content_arr in rows:
            virtual_path = self._virtual_path(storage_path)
            filename = PurePosixPath(virtual_path).name

            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue

            if isinstance(content_arr, list):
                lines = content_arr
            elif isinstance(content_arr, str):
                lines = json.loads(content_arr)
            else:
                lines = []

            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Sync wrapper for aglob_info."""
        return run_async_safely(
            self.aglob_info(pattern, path)
        )

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern.

        Narrows the SQL candidate set using the literal suffix of *pattern*
        (e.g. ``"*.py"`` → ``AND path LIKE '%.py'``) before applying
        ``fnmatch`` in Python, avoiding large unrelated result sets.
        """
        storage_prefix = self._storage_path(path)
        like_prefix = storage_prefix + "%" if storage_prefix else "%"

        # Extract a literal suffix from the pattern for SQL pre-filtering.
        # Only handles the common case: a single leading "*" followed by a
        # wildcard-free string (e.g. "*.py", "*.txt").  Complex patterns
        # (brace expansion, embedded wildcards) fall back to prefix-only SQL.
        stripped = pattern.lstrip("*")
        like_suffix: str | None = None
        if stripped and not any(c in stripped for c in "?[{*"):
            like_suffix = f"%{stripped}"

        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if like_suffix:
                    await cur.execute(
                        f"""
                        SELECT path, modified_at,
                               COALESCE(jsonb_array_length(content->'content'), 0)
                        FROM {self._table}
                        WHERE path LIKE %s AND path LIKE %s
                        ORDER BY path
                        """,
                        (like_prefix, like_suffix),
                    )
                else:
                    await cur.execute(
                        f"""
                        SELECT path, modified_at,
                               COALESCE(jsonb_array_length(content->'content'), 0)
                        FROM {self._table}
                        WHERE path LIKE %s
                        ORDER BY path
                        """,
                        (like_prefix,),
                    )
                rows = await cur.fetchall()

        results: list[FileInfo] = []
        for storage_path, modified_at, line_count in rows:
            virtual_path = self._virtual_path(storage_path)
            rel_path = (
                virtual_path[len(path) :].lstrip("/") if path != "/" else virtual_path[1:]
            )

            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(virtual_path, pattern):
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": line_count,
                        "modified_at": modified_at.isoformat() if modified_at else None,
                    }
                )

        results.sort(key=lambda x: x.get("path", ""))
        return results
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


# =============================================================================
# Azure Blob Storage Backend
# =============================================================================


@dataclass
class AzureBlobConfig:
    """Configuration for Azure Blob Storage."""

    container: str
    prefix: str = ""
    connection_string: str | None = None
    account_url: str | None = None
    credential: Any = None


class AzureBlobBackend(BackendProtocol):
    """Azure Blob Storage backend for Deep Agents file operations."""

    def __init__(self, config: AzureBlobConfig) -> None:
        self._config = config
        self._prefix = config.prefix.strip("/")
        if self._prefix:
            self._prefix += "/"
        self._service: BlobServiceClient | None = None
        self._service_loop: asyncio.AbstractEventLoop | None = None

    def _blob_name(self, path: str) -> str:
        return f"{self._prefix}{path.lstrip('/')}"

    def _virtual_path(self, blob_name: str) -> str:
        if self._prefix and blob_name.startswith(self._prefix):
            blob_name = blob_name[len(self._prefix) :]
        return _normalize_virtual_path(blob_name)

    async def close(self) -> None:
        """Close the underlying Azure clients."""
        if self._service is not None:
            await self._service.close()
            self._service = None

    async def _ensure_container_client(self):
        """Lazily initialize the Azure Blob clients inside an event loop."""
        loop = asyncio.get_running_loop()
        if self._service is not None and self._service_loop is not loop:
            await self._service.close()
            self._service = None
            self._service_loop = None

        if self._service is None:
            if self._config.connection_string:
                self._service = BlobServiceClient.from_connection_string(
                    self._config.connection_string
                )
            elif self._config.account_url:
                self._service = BlobServiceClient(
                    account_url=self._config.account_url,
                    credential=self._config.credential,
                )
            else:
                raise ValueError(
                    "AzureBlobConfig requires either connection_string or account_url"
                )
            self._service_loop = loop
        return self._service.get_container_client(self._config.container)

    async def ensure_container(self) -> None:
        """Create the configured container when it does not already exist."""
        try:
            container = await self._ensure_container_client()
            await container.create_container()
        except ResourceExistsError:
            pass

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        container = await self._ensure_container_client()
        blob = container.get_blob_client(self._blob_name(path))
        try:
            downloader = await blob.download_blob()
            payload = await downloader.readall()
        except ResourceNotFoundError:
            return None
        return json.loads(payload.decode("utf-8"))

    async def _put_file_data(
        self,
        path: str,
        data: dict[str, Any],
        *,
        update_modified: bool = True,
    ) -> None:
        if update_modified:
            data["modified_at"] = _utcnow_iso()
        container = await self._ensure_container_client()
        blob = container.get_blob_client(self._blob_name(path))
        await blob.upload_blob(
            json.dumps(data).encode("utf-8"),
            overwrite=True,
            content_type="application/json",
        )

    async def _exists(self, path: str) -> bool:
        container = await self._ensure_container_client()
        blob = container.get_blob_client(self._blob_name(path))
        return bool(await blob.exists())

    async def _list_blobs(self, prefix: str = "") -> list[tuple[str, int | None, str | None]]:
        blob_prefix = self._blob_name(prefix)
        results: list[tuple[str, int | None, str | None]] = []
        container = await self._ensure_container_client()
        async for blob in container.list_blobs(name_starts_with=blob_prefix):
            modified = blob.last_modified.isoformat() if blob.last_modified else None
            results.append((self._virtual_path(blob.name), getattr(blob, "size", 0), modified))
        return results

    def ls_info(self, path: str) -> list[FileInfo]:
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        return _build_direct_listing(path, await self._list_blobs(path))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return run_async_safely(self.aread(file_path, offset, limit))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _read_text_payload(file_path, await self._get_file_data(file_path), offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        return run_async_safely(self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        try:
            await self._put_file_data(file_path, _make_text_file_data(content), update_modified=False)
            return WriteResult(path=file_path, files_update=None)
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
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
        updated, occurrences, error = _edit_text_payload(
            await self._get_file_data(file_path),
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        if error == "file_not_found":
            return EditResult(error=f"Error: File '{file_path}' not found")
        if error:
            return EditResult(error=error)

        try:
            await self._put_file_data(file_path, updated or {})
            return EditResult(path=file_path, files_update=None, occurrences=occurrences or 0)
        except Exception as exc:
            return EditResult(error=f"Error editing file '{file_path}': {exc}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return run_async_safely(self.agrep_raw(pattern, path, glob))

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"

        matches: list[GrepMatch] = []
        for virtual_path, _size, _modified in await self._list_blobs(path or "/"):
            filename = PurePosixPath(virtual_path).name
            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue

            data = await self._get_file_data(virtual_path)
            if data is None:
                continue

            for line_num, line in enumerate(data.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return run_async_safely(self.aglob_info(pattern, path))

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        results: list[FileInfo] = []
        for virtual_path, size, modified_at in await self._list_blobs(path):
            if _matches_glob(pattern, path, virtual_path):
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": size or 0,
                        "modified_at": modified_at,
                    }
                )
        results.sort(key=lambda item: item.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            container = await self._ensure_container_client()
            blob = container.get_blob_client(self._blob_name(path))
            try:
                await blob.upload_blob(
                    content,
                    overwrite=True,
                    content_type="application/octet-stream",
                )
                responses.append(FileUploadResponse(path=path, error=None))
            except ResourceNotFoundError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            container = await self._ensure_container_client()
            blob = container.get_blob_client(self._blob_name(path))
            try:
                downloader = await blob.download_blob()
                content = await downloader.readall()
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except ResourceNotFoundError:
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="file_not_found")
                )
            except Exception:
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
        return responses


# =============================================================================
# Google Cloud Storage Backend
# =============================================================================


@dataclass
class GCSConfig:
    """Configuration for Google Cloud Storage."""

    bucket: str
    prefix: str = ""
    service_file: str | None = None
    api_root: str | None = None


class GCSBackend(BackendProtocol):
    """Google Cloud Storage backend for Deep Agents file operations."""

    def __init__(self, config: GCSConfig) -> None:
        self._config = config
        self._prefix = config.prefix.strip("/")
        if self._prefix:
            self._prefix += "/"
        self._storage: GCSStorage | None = None
        self._storage_loop: asyncio.AbstractEventLoop | None = None
        self._bucket = config.bucket

    def _object_name(self, path: str) -> str:
        return f"{self._prefix}{path.lstrip('/')}"

    def _virtual_path(self, object_name: str) -> str:
        if self._prefix and object_name.startswith(self._prefix):
            object_name = object_name[len(self._prefix) :]
        return _normalize_virtual_path(object_name)

    async def close(self) -> None:
        """Close the underlying GCS session."""
        if self._storage is not None:
            await self._storage.close()
            self._storage = None

    async def _ensure_storage(self) -> GCSStorage:
        """Lazily initialize the underlying GCS client inside an event loop."""
        loop = asyncio.get_running_loop()
        if self._storage is not None and self._storage_loop is not loop:
            await self._storage.close()
            self._storage = None
            self._storage_loop = None

        if self._storage is None:
            self._storage = GCSStorage(
                service_file=self._config.service_file,
                api_root=self._config.api_root,
            )
            self._storage_loop = loop
        return self._storage

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        try:
            storage = await self._ensure_storage()
            payload = await storage.download(
                self._bucket, self._object_name(path)
            )
        except Exception as exc:
            if _status_code_from_error(exc) in {404, 410}:
                return None
            raise
        return json.loads(payload.decode("utf-8"))

    async def _put_file_data(
        self,
        path: str,
        data: dict[str, Any],
        *,
        update_modified: bool = True,
    ) -> None:
        if update_modified:
            data["modified_at"] = _utcnow_iso()
        storage = await self._ensure_storage()
        await storage.upload(
            self._bucket,
            self._object_name(path),
            json.dumps(data).encode("utf-8"),
            content_type="application/json",
        )

    async def _exists(self, path: str) -> bool:
        try:
            storage = await self._ensure_storage()
            await storage.download_metadata(
                self._bucket, self._object_name(path)
            )
            return True
        except Exception as exc:
            if _status_code_from_error(exc) in {404, 410}:
                return False
            raise

    async def _list_objects(self, prefix: str = "") -> list[tuple[str, int | None, str | None]]:
        params: dict[str, str] = {"prefix": self._object_name(prefix), "pageToken": ""}
        results: list[tuple[str, int | None, str | None]] = []

        while True:
            storage = await self._ensure_storage()
            content = await storage.list_objects(self._bucket, params=params)
            for item in content.get("items", []):
                results.append(
                    (
                        self._virtual_path(item["name"]),
                        int(item.get("size", 0)),
                        item.get("updated"),
                    )
                )
            page_token = content.get("nextPageToken", "")
            if not page_token:
                break
            params["pageToken"] = page_token

        return results

    def ls_info(self, path: str) -> list[FileInfo]:
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        return _build_direct_listing(path, await self._list_objects(path))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return run_async_safely(self.aread(file_path, offset, limit))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _read_text_payload(file_path, await self._get_file_data(file_path), offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        return run_async_safely(self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        try:
            await self._put_file_data(file_path, _make_text_file_data(content), update_modified=False)
            return WriteResult(path=file_path, files_update=None)
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
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
        updated, occurrences, error = _edit_text_payload(
            await self._get_file_data(file_path),
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        if error == "file_not_found":
            return EditResult(error=f"Error: File '{file_path}' not found")
        if error:
            return EditResult(error=error)

        try:
            await self._put_file_data(file_path, updated or {})
            return EditResult(path=file_path, files_update=None, occurrences=occurrences or 0)
        except Exception as exc:
            return EditResult(error=f"Error editing file '{file_path}': {exc}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return run_async_safely(self.agrep_raw(pattern, path, glob))

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"

        matches: list[GrepMatch] = []
        for virtual_path, _size, _modified in await self._list_objects(path or "/"):
            filename = PurePosixPath(virtual_path).name
            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue

            data = await self._get_file_data(virtual_path)
            if data is None:
                continue

            for line_num, line in enumerate(data.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return run_async_safely(self.aglob_info(pattern, path))

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        results: list[FileInfo] = []
        for virtual_path, size, modified_at in await self._list_objects(path):
            if _matches_glob(pattern, path, virtual_path):
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": size or 0,
                        "modified_at": modified_at,
                    }
                )
        results.sort(key=lambda item: item.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                storage = await self._ensure_storage()
                await storage.upload(
                    self._bucket,
                    self._object_name(path),
                    content,
                    content_type="application/octet-stream",
                )
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                storage = await self._ensure_storage()
                content = await storage.download(
                    self._bucket, self._object_name(path)
                )
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception as exc:
                error = (
                    "file_not_found"
                    if _status_code_from_error(exc) in {404, 410}
                    else "invalid_path"
                )
                responses.append(FileDownloadResponse(path=path, content=None, error=error))
        return responses


# =============================================================================
# MongoDB Backend
# =============================================================================


@dataclass
class MongoDBConfig:
    """Configuration for MongoDB storage."""

    connection_uri: str = "mongodb://localhost:27017"
    database: str = "deepagents"
    collection: str = "files"
    prefix: str = ""
    server_selection_timeout_ms: int = 5000


class MongoDBBackend(BackendProtocol):
    """MongoDB backend for Deep Agents file operations."""

    def __init__(self, config: MongoDBConfig) -> None:
        self._config = config
        self._prefix = config.prefix.strip("/")
        if self._prefix:
            self._prefix += "/"
        self._client: AsyncIOMotorClient | None = None
        self._collection = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._initialized = False

    def _storage_path(self, path: str) -> str:
        return f"{self._prefix}{path.lstrip('/')}"

    def _virtual_path(self, path: str) -> str:
        if self._prefix and path.startswith(self._prefix):
            path = path[len(self._prefix) :]
        return _normalize_virtual_path(path)

    async def initialize(self) -> None:
        """Create indexes used by the backend."""
        collection = await self._ensure_collection()
        if self._initialized:
            return
        await collection.create_index("path", unique=True)
        await collection.create_index("modified_at")
        self._initialized = True

    async def close(self) -> None:
        """Close the MongoDB client."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._collection = None
            self._client_loop = None
            self._initialized = False

    async def _ensure_collection(self):
        """Lazily initialize the MongoDB client inside an event loop."""
        loop = asyncio.get_running_loop()
        if self._client is not None and self._client_loop is not loop:
            self._client.close()
            self._client = None
            self._collection = None
            self._client_loop = None
            self._initialized = False

        if self._client is None:
            self._client = AsyncIOMotorClient(
                self._config.connection_uri,
                serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
            )
            self._collection = self._client[self._config.database][self._config.collection]
            self._client_loop = loop

        return self._collection

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        collection = await self._ensure_collection()
        document = await collection.find_one({"path": self._storage_path(path)})
        if document is None:
            return None
        return {
            "content": document.get("content", []),
            "created_at": (
                document.get("created_at").isoformat() if document.get("created_at") else None
            ),
            "modified_at": (
                document.get("modified_at").isoformat() if document.get("modified_at") else None
            ),
        }

    async def _put_file_data(
        self,
        path: str,
        data: dict[str, Any],
        *,
        update_modified: bool = True,
    ) -> None:
        storage_path = self._storage_path(path)
        now = datetime.now(timezone.utc)
        collection = await self._ensure_collection()
        existing = await collection.find_one({"path": storage_path}, {"created_at": 1})
        created_at = existing.get("created_at") if existing else now
        document = {
            "path": storage_path,
            "content": data.get("content", []),
            "created_at": created_at,
            "modified_at": now if update_modified else created_at,
        }
        await collection.replace_one({"path": storage_path}, document, upsert=True)

    async def _exists(self, path: str) -> bool:
        collection = await self._ensure_collection()
        return bool(await collection.find_one({"path": self._storage_path(path)}, {"_id": 1}))

    async def _list_documents(self, path: str = "/") -> list[tuple[str, int | None, str | None]]:
        storage_prefix = self._storage_path(path)
        regex = f"^{re.escape(storage_prefix)}"
        results: list[tuple[str, int | None, str | None]] = []
        collection = await self._ensure_collection()
        cursor = collection.find({"path": {"$regex": regex}})
        async for document in cursor:
            results.append(
                (
                    self._virtual_path(document["path"]),
                    len(document.get("content", [])),
                    document.get("modified_at").isoformat() if document.get("modified_at") else None,
                )
            )
        return results

    def ls_info(self, path: str) -> list[FileInfo]:
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        return _build_direct_listing(path, await self._list_documents(path))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return run_async_safely(self.aread(file_path, offset, limit))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _read_text_payload(file_path, await self._get_file_data(file_path), offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        return run_async_safely(self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        try:
            await self._put_file_data(file_path, _make_text_file_data(content), update_modified=False)
            return WriteResult(path=file_path, files_update=None)
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
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
        updated, occurrences, error = _edit_text_payload(
            await self._get_file_data(file_path),
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        if error == "file_not_found":
            return EditResult(error=f"Error: File '{file_path}' not found")
        if error:
            return EditResult(error=error)

        try:
            await self._put_file_data(file_path, updated or {})
            return EditResult(path=file_path, files_update=None, occurrences=occurrences or 0)
        except Exception as exc:
            return EditResult(error=f"Error editing file '{file_path}': {exc}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return run_async_safely(self.agrep_raw(pattern, path, glob))

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"

        storage_prefix = self._storage_path(path or "/")
        matches: list[GrepMatch] = []
        collection = await self._ensure_collection()
        cursor = collection.find({"path": {"$regex": f"^{re.escape(storage_prefix)}"}})
        async for document in cursor:
            virtual_path = self._virtual_path(document["path"])
            filename = PurePosixPath(virtual_path).name
            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue
            for line_num, line in enumerate(document.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return run_async_safely(self.aglob_info(pattern, path))

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        results: list[FileInfo] = []
        collection = await self._ensure_collection()
        cursor = collection.find({"path": {"$regex": f"^{re.escape(self._storage_path(path))}"}})
        async for document in cursor:
            virtual_path = self._virtual_path(document["path"])
            if _matches_glob(pattern, path, virtual_path):
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": len(document.get("content", [])),
                        "modified_at": (
                            document.get("modified_at").isoformat()
                            if document.get("modified_at")
                            else None
                        ),
                    }
                )
        results.sort(key=lambda item: item.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                await self._put_file_data(
                    path,
                    _make_text_file_data(content.decode("utf-8", errors="replace")),
                    update_modified=False,
                )
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                data = await self._get_file_data(path)
                if data is None:
                    responses.append(
                        FileDownloadResponse(path=path, content=None, error="file_not_found")
                    )
                    continue
                content = "\n".join(data.get("content", [])).encode("utf-8")
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception:
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
        return responses


# =============================================================================
# Redis / Valkey Backend
# =============================================================================


@dataclass
class RedisConfig:
    """Configuration for Redis/Valkey storage."""

    url: str = "redis://localhost:6379/0"
    prefix: str = ""
    namespace: str = "deepagents"


class RedisBackend(BackendProtocol):
    """Redis/Valkey backend for Deep Agents file operations."""

    def __init__(self, config: RedisConfig) -> None:
        self._config = config
        self._prefix = config.prefix.strip("/")
        if self._prefix:
            self._prefix += "/"
        self._client = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._namespace = config.namespace
        self._index_key = f"{self._namespace}:__index__"

    def _storage_path(self, path: str) -> str:
        return f"{self._prefix}{path.lstrip('/')}"

    def _virtual_path(self, storage_path: str) -> str:
        if self._prefix and storage_path.startswith(self._prefix):
            storage_path = storage_path[len(self._prefix) :]
        return _normalize_virtual_path(storage_path)

    def _data_key(self, path: str) -> str:
        return f"{self._namespace}:file:{self._storage_path(path)}"

    async def close(self) -> None:
        """Close the Redis client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._client_loop = None

    async def _ensure_client(self):
        """Lazily initialize the Redis client inside an event loop."""
        loop = asyncio.get_running_loop()
        if self._client is not None and self._client_loop is not loop:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass
            self._client = None
            self._client_loop = None

        if self._client is None:
            self._client = redis.from_url(self._config.url, decode_responses=False)
            self._client_loop = loop
        return self._client

    async def _get_file_data(self, path: str) -> dict[str, Any] | None:
        client = await self._ensure_client()
        payload = await client.get(self._data_key(path))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    async def _put_file_data(
        self,
        path: str,
        data: dict[str, Any],
        *,
        update_modified: bool = True,
    ) -> None:
        if update_modified:
            data["modified_at"] = _utcnow_iso()
        storage_path = self._storage_path(path)
        client = await self._ensure_client()
        await client.set(
            f"{self._namespace}:file:{storage_path}",
            json.dumps(data).encode("utf-8"),
        )
        await client.sadd(self._index_key, storage_path)

    async def _exists(self, path: str) -> bool:
        client = await self._ensure_client()
        return bool(await client.exists(self._data_key(path)))

    async def _list_paths(self, path: str = "/") -> list[tuple[str, int | None, str | None]]:
        storage_prefix = self._storage_path(path)
        client = await self._ensure_client()
        members = await client.smembers(self._index_key)
        storage_paths = sorted(
            (
                member.decode("utf-8") if isinstance(member, bytes) else str(member)
                for member in members
            ),
            key=str,
        )
        matching = [
            storage_path
            for storage_path in storage_paths
            if storage_path.startswith(storage_prefix)
        ]
        payloads = await client.mget(
            [f"{self._namespace}:file:{storage_path}" for storage_path in matching]
        )

        results: list[tuple[str, int | None, str | None]] = []
        for storage_path, payload in zip(matching, payloads, strict=False):
            if payload is None:
                continue
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            data = json.loads(payload)
            results.append(
                (
                    self._virtual_path(storage_path),
                    len(data.get("content", [])),
                    data.get("modified_at"),
                )
            )
        return results

    def ls_info(self, path: str) -> list[FileInfo]:
        return run_async_safely(self.als_info(path))

    async def als_info(self, path: str) -> list[FileInfo]:
        return _build_direct_listing(path, await self._list_paths(path))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return run_async_safely(self.aread(file_path, offset, limit))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _read_text_payload(file_path, await self._get_file_data(file_path), offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        return run_async_safely(self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        if await self._exists(file_path):
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        try:
            await self._put_file_data(file_path, _make_text_file_data(content), update_modified=False)
            return WriteResult(path=file_path, files_update=None)
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
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
        updated, occurrences, error = _edit_text_payload(
            await self._get_file_data(file_path),
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        if error == "file_not_found":
            return EditResult(error=f"Error: File '{file_path}' not found")
        if error:
            return EditResult(error=error)

        try:
            await self._put_file_data(file_path, updated or {})
            return EditResult(path=file_path, files_update=None, occurrences=occurrences or 0)
        except Exception as exc:
            return EditResult(error=f"Error editing file '{file_path}': {exc}")

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return run_async_safely(self.agrep_raw(pattern, path, glob))

    async def agrep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"

        matches: list[GrepMatch] = []
        for virtual_path, _size, _modified in await self._list_paths(path or "/"):
            filename = PurePosixPath(virtual_path).name
            if glob and not wcglob.globmatch(filename, glob, flags=wcglob.BRACE):
                continue
            data = await self._get_file_data(virtual_path)
            if data is None:
                continue
            for line_num, line in enumerate(data.get("content", []), 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return run_async_safely(self.aglob_info(pattern, path))

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        results: list[FileInfo] = []
        for virtual_path, size, modified_at in await self._list_paths(path):
            if _matches_glob(pattern, path, virtual_path):
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": size or 0,
                        "modified_at": modified_at,
                    }
                )
        results.sort(key=lambda item: item.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return run_async_safely(self.aupload_files(files))

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                await self._put_file_data(
                    path,
                    _make_text_file_data(content.decode("utf-8", errors="replace")),
                    update_modified=False,
                )
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return run_async_safely(self.adownload_files(paths))

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                data = await self._get_file_data(path)
                if data is None:
                    responses.append(
                        FileDownloadResponse(path=path, content=None, error="file_not_found")
                    )
                    continue
                content = "\n".join(data.get("content", [])).encode("utf-8")
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception:
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
        return responses
