import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from deepagents_backends import S3Backend
from tests.scalability import (
    GLOB_MATCH_SUFFIX,
    GLOB_NOMATCH_SUFFIX,
    GREP_MATCH_LINE,
    GREP_NOMATCH_LINE,
    LARGE_FLAT_FILES,
    LARGE_NESTED_DIRS,
)


@pytest.mark.unit
class TestS3BackendUnit:
    @pytest.fixture
    def mock_s3_client(self):
        with patch("aioboto3.Session") as mock_session:
            mock_client = AsyncMock()
            mock_session.return_value.client.return_value.__aenter__.return_value = mock_client
            
            # Fix: get_paginator is synchronous
            mock_client.get_paginator = MagicMock()
            
            yield mock_client

    @pytest.fixture
    def backend(self, s3_config_unit, mock_s3_client):
        # Trigger initialization that creates the session
        return S3Backend(s3_config_unit)

    async def test_aread_file_exists(self, backend, mock_s3_client):
        content = json.dumps({"content": ["line1", "line2"]}).encode("utf-8")
        
        # Setup body stream mock
        mock_body = AsyncMock()
        mock_body.read.return_value = content
        mock_body.__aenter__.return_value = mock_body
        
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        result = await backend.aread("test.txt")
        assert "1\tline1" in result
        assert "2\tline2" in result
        
        mock_s3_client.get_object.assert_called_with(
            Bucket="unit-test-bucket", 
            Key="unit-test/test.txt"
        )

    async def test_aread_file_not_found(self, backend, mock_s3_client):
        error_response = {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}
        mock_s3_client.get_object.side_effect = ClientError(error_response, "GetObject")

        result = await backend.aread("nonexistent.txt")
        assert "Error: File 'nonexistent.txt' not found" in result

    async def test_awrite_success(self, backend, mock_s3_client):
        # Mock _exists to return False
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        
        result = await backend.awrite("new.txt", "content")
        assert result.error is None
        assert result.path == "new.txt"
        mock_s3_client.put_object.assert_called_once()

    async def test_awrite_already_exists(self, backend, mock_s3_client):
        mock_s3_client.head_object.return_value = {}
        
        result = await backend.awrite("exists.txt", "content")
        assert result.error is not None
        assert "already exists" in result.error

    async def test_als_info(self, backend, mock_s3_client):
        paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = paginator

        lm = MagicMock()
        lm.isoformat.return_value = "2023-01-01T00:00:00Z"
        # With Delimiter="/", direct files land in Contents and virtual
        # sub-directories land in CommonPrefixes — no nested file objects.
        page1 = {
            "Contents": [
                {"Key": "unit-test/file1.txt", "Size": 100, "LastModified": lm},
            ],
            "CommonPrefixes": [
                {"Prefix": "unit-test/dir/"},
            ],
        }

        async def async_pages(*args, **kwargs):
            yield page1

        paginator.paginate.return_value = async_pages()

        results = await backend.als_info("/")

        assert len(results) == 2
        paths = {r["path"] for r in results}
        assert "/file1.txt" in paths
        assert "/dir/" in paths
        # Verify delimiter was passed
        paginator.paginate.assert_called_once()
        call_kwargs = paginator.paginate.call_args.kwargs
        assert call_kwargs.get("Delimiter") == "/"


@pytest.mark.unit
class TestS3BackendScalability:
    """Large-candidate-set correctness tests (mocked, no real I/O).

    These tests exercise the acceptance invariants documented in
    ``tests/scalability.py`` against mocked S3 responses.  Optimization PRs
    must not regress these assertions.
    """

    # S3Config unit prefix is "unit-test/"
    _PREFIX = "unit-test"

    @pytest.fixture
    def mock_s3_client(self):
        with patch("aioboto3.Session") as mock_session:
            mock_client = AsyncMock()
            mock_session.return_value.client.return_value.__aenter__.return_value = mock_client
            mock_client.get_paginator = MagicMock()
            yield mock_client

    @pytest.fixture
    def backend(self, s3_config_unit, mock_s3_client):
        return S3Backend(s3_config_unit)

    def _make_s3_object(self, virtual_path: str) -> dict:
        """Build a fake S3 Contents entry for *virtual_path*."""
        key = f"{self._PREFIX}{virtual_path}"
        lm = MagicMock()
        lm.isoformat.return_value = "2024-01-01T00:00:00+00:00"
        return {"Key": key, "Size": 10, "LastModified": lm}

    def _setup_paginator(
        self,
        mock_s3_client,
        direct_file_paths: list[str],
        subdir_prefixes: list[str] | None = None,
    ) -> None:
        """Set up paginator to return delimiter-aware pages.

        *direct_file_paths* are virtual paths of direct file children
        (returned in ``Contents``).  *subdir_prefixes* are virtual paths
        of direct subdirectory entries, e.g. ``["/root/dir_000/"]``
        (returned in ``CommonPrefixes``).
        """
        paginator = MagicMock()
        mock_s3_client.get_paginator.return_value = paginator
        objects = [self._make_s3_object(p) for p in direct_file_paths]
        common_prefixes = [
            {"Prefix": f"{self._PREFIX}{p}"} for p in (subdir_prefixes or [])
        ]

        async def async_pages(*args, **kwargs):
            yield {"Contents": objects, "CommonPrefixes": common_prefixes}

        paginator.paginate.return_value = async_pages()

    def _make_body(self, lines: list[str]) -> AsyncMock:
        data = json.dumps({"content": lines}).encode()
        body = AsyncMock()
        body.read.return_value = data
        body.__aenter__ = AsyncMock(return_value=body)
        body.__aexit__ = AsyncMock(return_value=None)
        return body

    # ── als_info: flat directory ──────────────────────────────────────────────

    async def test_als_info_returns_only_direct_children_from_large_flat_tree(
        self, backend, mock_s3_client, large_flat_paths
    ):
        """Invariant 1a: all direct-child files reported, no extras."""
        # With Delimiter="/", S3 returns flat files in Contents only.
        self._setup_paginator(mock_s3_client, large_flat_paths, subdir_prefixes=[])
        results = await backend.als_info("/large_flat")

        assert len(results) == LARGE_FLAT_FILES
        assert all(not r["is_dir"] for r in results)
        assert all(r["path"].startswith("/large_flat/") for r in results)
        assert all("/" not in r["path"].removeprefix("/large_flat/") for r in results)

    # ── als_info: nested tree ─────────────────────────────────────────────────

    async def test_als_info_returns_only_directory_entries_from_large_nested_tree(
        self, backend, mock_s3_client
    ):
        """Invariant 1b: with Delimiter='/', nested files appear only via CommonPrefixes."""
        # With Delimiter="/", S3 returns no Contents (all files are nested)
        # and 10 CommonPrefixes entries.
        subdir_prefixes = [
            f"/large_nested/dir_{d:03d}/" for d in range(LARGE_NESTED_DIRS)
        ]
        self._setup_paginator(mock_s3_client, [], subdir_prefixes=subdir_prefixes)
        results = await backend.als_info("/large_nested")

        assert len(results) == LARGE_NESTED_DIRS
        assert all(r["is_dir"] for r in results)
        dir_paths = {r["path"] for r in results}
        for d in range(LARGE_NESTED_DIRS):
            assert f"/large_nested/dir_{d:03d}/" in dir_paths

    # ── agrep_raw: large candidate set ───────────────────────────────────────

    async def test_agrep_raw_returns_only_matching_files_from_large_set(
        self, backend, mock_s3_client, grep_dataset
    ):
        """Invariant 2: no false positives, no false negatives."""
        matching_paths, all_paths = grep_dataset
        self._setup_paginator(mock_s3_client, all_paths)

        matching_keys = {f"{self._PREFIX}{p}" for p in matching_paths}

        async def get_object_effect(*, Bucket, Key):
            lines = [GREP_MATCH_LINE] if Key in matching_keys else [GREP_NOMATCH_LINE]
            return {"Body": self._make_body(lines)}

        mock_s3_client.get_object.side_effect = get_object_effect

        results = await backend.agrep_raw(GREP_MATCH_LINE, "/large_grep")

        assert isinstance(results, list)
        assert len(results) == len(matching_paths)
        result_paths = {r["path"] for r in results}
        assert result_paths == set(matching_paths)

    # ── aglob_info: large candidate set ──────────────────────────────────────

    async def test_aglob_info_returns_only_matching_files_from_large_set(
        self, backend, mock_s3_client, glob_dataset
    ):
        """Invariant 3: only files matching the glob pattern appear in results."""
        matching_paths, all_paths = glob_dataset
        self._setup_paginator(mock_s3_client, all_paths)

        results = await backend.aglob_info(f"*{GLOB_MATCH_SUFFIX}", "/large_glob")

        assert len(results) == len(matching_paths)
        result_paths = {r["path"] for r in results}
        assert result_paths == set(matching_paths)
        assert all(GLOB_NOMATCH_SUFFIX not in r["path"] for r in results)
