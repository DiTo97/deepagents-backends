import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import deepagents_backends
from deepagents_backends import PostgresBackend
from tests.scalability import (
    GLOB_MATCH_SUFFIX,
    GLOB_NOMATCH_SUFFIX,
    GREP_MATCH_LINE,
    GREP_NOMATCH_LINE,
    LARGE_FLAT_FILES,
    LARGE_NESTED_DIRS,
)


@pytest.mark.unit
class TestPostgresBackendUnit:
    @pytest.fixture
    def mock_pool(self):
        with patch("psycopg_pool.AsyncConnectionPool", new_callable=MagicMock) as mock_pool_cls:
            pool_instance = MagicMock()
            mock_pool_cls.return_value = pool_instance

            # Setup connection context
            # pool.connection() is synchronous but returns an async context manager
            mock_conn_ctx = MagicMock()
            pool_instance.connection = MagicMock(return_value=mock_conn_ctx)
            mock_conn = MagicMock()
            mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

            # Setup cursor context
            # conn.cursor() is synchronous but returns an async context manager
            mock_cur_ctx = MagicMock()
            mock_conn.cursor = MagicMock(return_value=mock_cur_ctx)
            mock_cur = AsyncMock()
            mock_cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
            mock_cur_ctx.__aexit__ = AsyncMock(return_value=None)

            # conn.execute is async
            mock_conn.execute = AsyncMock()
            mock_conn.commit = AsyncMock()

            yield pool_instance, mock_conn, mock_cur

    @pytest.fixture
    async def backend(self, postgres_config_unit, mock_pool):
        backend = PostgresBackend(postgres_config_unit)
        pool_instance, _, _ = mock_pool
        backend._pool = pool_instance
        backend._initialized = True # Skip initialization query
        return backend

    async def test_aread_success(self, backend, mock_pool):
        _, _, mock_cur = mock_pool

        content = {"content": ["line1", "line2"]}
        # Mock fetching file data
        mock_cur.fetchone.return_value = [json.dumps(content), None, None]

        result = await backend.aread("test.txt")
        assert "1\tline1" in result
        assert "2\tline2" in result

        # Verify query was executed
        assert mock_cur.execute.called

    async def test_aread_file_not_found(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        mock_cur.fetchone.return_value = None

        result = await backend.aread("nonexistent.txt")
        assert "Error: File 'nonexistent.txt' not found" in result

    async def test_awrite_success(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        # Mock _exists to return False (None)
        mock_cur.fetchone.return_value = None

        result = await backend.awrite("new.txt", "content")
        assert result.error is None
        assert result.path == "new.txt"

        # Verify insert query was executed
        assert mock_pool[1].execute.called

    async def test_awrite_already_exists(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        # Mock _exists to return True (Row)
        mock_cur.fetchone.return_value = (1,)

        result = await backend.awrite("exists.txt", "content")
        assert result.error is not None
        assert "already exists" in result.error

    async def test_als_info_mixed(self, backend, mock_pool):
        """als_info correctly reports direct files and collapses nested paths."""
        _, _, mock_cur = mock_pool
        # als_info now issues two queries: direct-files fetchall, then dirs fetchall
        mock_cur.fetchall.side_effect = [
            [("file1.txt", None, 2)],  # direct files under root
            [("dir",)],                # distinct first segment of nested paths
        ]

        results = await backend.als_info("/")
        paths = {r["path"] for r in results}
        assert "/file1.txt" in paths
        assert "/dir/" in paths
        assert not any(r["is_dir"] for r in results if r["path"] == "/file1.txt")
        assert any(r["is_dir"] for r in results if r["path"] == "/dir/")

    @pytest.mark.parametrize(
        ("method_name", "args", "expected_coroutine_name"),
        [
            ("read", ("test.txt",), "aread"),
            ("write", ("new.txt", "content"), "awrite"),
            ("edit", ("test.txt", "old", "new"), "aedit"),
            ("ls_info", ("/",), "als_info"),
            ("grep_raw", ("pattern",), "agrep_raw"),
            ("glob_info", ("*.py",), "aglob_info"),
            ("upload_files", ([("file.txt", b"data")],), "aupload_files"),
            ("download_files", (["file.txt"],), "adownload_files"),
        ],
    )
    def test_sync_wrappers_delegate_to_run_async_safely(
        self, backend, method_name, args, expected_coroutine_name
    ):
        sentinel = object()

        with patch.object(deepagents_backends, "run_async_safely", return_value=sentinel) as mock_run:
            result = getattr(backend, method_name)(*args)

        assert result is sentinel

        coroutine = mock_run.call_args.args[0]
        try:
            assert coroutine.cr_code.co_name == expected_coroutine_name
        finally:
            coroutine.close()

    async def test_aupload_files_success(self, backend, mock_pool):
        responses = await backend.aupload_files([("data/config.json", b"line1\nline2")])

        assert len(responses) == 1
        assert responses[0].path == "data/config.json"
        assert responses[0].error is None
        assert mock_pool[1].execute.called
        assert mock_pool[1].commit.called

        _, params = mock_pool[1].execute.call_args.args
        assert params[0] == "data/config.json"
        assert json.loads(params[1]) == {"content": ["line1", "line2"]}

    async def test_aupload_files_invalid_path_on_exception(self, backend, mock_pool):
        mock_pool[1].execute.side_effect = RuntimeError("boom")

        responses = await backend.aupload_files([("broken.txt", b"oops")])

        assert len(responses) == 1
        assert responses[0].path == "broken.txt"
        assert responses[0].error == "invalid_path"
        assert mock_pool[1].commit.called

    async def test_adownload_files_success(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        mock_cur.fetchone.return_value = ({"content": ["line1", "line2"]},)

        responses = await backend.adownload_files(["data/config.json"])

        assert len(responses) == 1
        assert responses[0].path == "data/config.json"
        assert responses[0].content == b"line1\nline2"
        assert responses[0].error is None

    async def test_adownload_files_file_not_found(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        mock_cur.fetchone.return_value = None

        responses = await backend.adownload_files(["missing.txt"])

        assert len(responses) == 1
        assert responses[0].path == "missing.txt"
        assert responses[0].content is None
        assert responses[0].error == "file_not_found"

    async def test_adownload_files_invalid_path_on_exception(self, backend, mock_pool):
        _, _, mock_cur = mock_pool
        mock_cur.execute.side_effect = RuntimeError("boom")

        responses = await backend.adownload_files(["broken.txt"])

        assert len(responses) == 1
        assert responses[0].path == "broken.txt"
        assert responses[0].content is None
        assert responses[0].error == "invalid_path"


@pytest.mark.unit
class TestPostgresBackendScalability:
    """Large-candidate-set correctness tests (mocked, no real I/O).

    These tests exercise the acceptance invariants documented in
    ``tests/scalability.py`` against mocked PostgreSQL responses.
    Optimization PRs must not regress these assertions.
    """

    @pytest.fixture
    def mock_pool(self):
        with patch("psycopg_pool.AsyncConnectionPool", new_callable=MagicMock) as mock_pool_cls:
            pool_instance = MagicMock()
            mock_pool_cls.return_value = pool_instance

            mock_conn_ctx = MagicMock()
            pool_instance.connection = MagicMock(return_value=mock_conn_ctx)
            mock_conn = MagicMock()
            mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_cur_ctx = MagicMock()
            mock_conn.cursor = MagicMock(return_value=mock_cur_ctx)
            mock_cur = AsyncMock()
            mock_cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
            mock_cur_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_conn.execute = AsyncMock()
            mock_conn.commit = AsyncMock()

            yield pool_instance, mock_conn, mock_cur

    @pytest.fixture
    async def backend(self, postgres_config_unit, mock_pool):
        backend = PostgresBackend(postgres_config_unit)
        pool_instance, _, _ = mock_pool
        backend._pool = pool_instance
        backend._initialized = True
        return backend

    def _make_list_rows(self, virtual_paths: list[str]) -> list[tuple]:
        """Build _list_paths-style rows: (storage_path, modified_at, line_count)."""
        return [(p.lstrip("/"), None, 1) for p in virtual_paths]

    # ── als_info: flat directory ──────────────────────────────────────────────

    async def test_als_info_returns_only_direct_children_from_large_flat_tree(
        self, backend, mock_pool, large_flat_paths
    ):
        """Invariant 1a: all direct-child files reported, no extras."""
        _, _, mock_cur = mock_pool
        # New SQL-based als_info issues two fetchall calls:
        #   1st: direct file rows (paths not nested further)
        #   2nd: distinct dir-name rows (empty here — no subdirs)
        file_rows = [(p.lstrip("/"), None, 1) for p in large_flat_paths]
        mock_cur.fetchall.side_effect = [file_rows, []]

        results = await backend.als_info("/large_flat")

        assert len(results) == LARGE_FLAT_FILES
        assert all(not r["is_dir"] for r in results)
        assert all(r["path"].startswith("/large_flat/") for r in results)
        assert all("/" not in r["path"].removeprefix("/large_flat/") for r in results)

    # ── als_info: nested tree ─────────────────────────────────────────────────

    async def test_als_info_returns_only_directory_entries_from_large_nested_tree(
        self, backend, mock_pool, large_nested_paths
    ):
        """Invariant 1b: nested files collapse to their parent directory entries."""
        _, _, mock_cur = mock_pool
        # 1st fetchall: no direct files under /large_nested/
        # 2nd fetchall: DISTINCT first segment → 10 unique dir names
        dir_name_rows = [(f"dir_{d:03d}",) for d in range(LARGE_NESTED_DIRS)]
        mock_cur.fetchall.side_effect = [[], dir_name_rows]

        results = await backend.als_info("/large_nested")

        assert len(results) == LARGE_NESTED_DIRS
        assert all(r["is_dir"] for r in results)
        dir_paths = {r["path"] for r in results}
        for d in range(LARGE_NESTED_DIRS):
            assert f"/large_nested/dir_{d:03d}/" in dir_paths

    # ── agrep_raw: large candidate set ───────────────────────────────────────

    async def test_agrep_raw_returns_only_matching_files_from_large_set(
        self, backend, mock_pool, grep_dataset
    ):
        """Invariant 2: no false positives, no false negatives."""
        matching_paths, all_paths = grep_dataset
        _, _, mock_cur = mock_pool

        matching_virtual = set(matching_paths)

        # New agrep_raw: single fetchall returning (storage_path, content_list) rows.
        mock_cur.fetchall.return_value = [
            (
                p.lstrip("/"),
                [GREP_MATCH_LINE] if p in matching_virtual else [GREP_NOMATCH_LINE],
            )
            for p in all_paths
        ]

        results = await backend.agrep_raw(GREP_MATCH_LINE, "/large_grep")

        assert isinstance(results, list)
        assert len(results) == len(matching_paths)
        result_paths = {r["path"] for r in results}
        assert result_paths == set(matching_paths)

    # ── aglob_info: large candidate set ──────────────────────────────────────

    async def test_aglob_info_returns_only_matching_files_from_large_set(
        self, backend, mock_pool, glob_dataset
    ):
        """Invariant 3: only files matching the glob pattern appear in results."""
        matching_paths, all_paths = glob_dataset
        _, _, mock_cur = mock_pool
        mock_cur.fetchall.return_value = self._make_list_rows(all_paths)

        results = await backend.aglob_info(f"*{GLOB_MATCH_SUFFIX}", "/large_glob")

        assert len(results) == len(matching_paths)
        result_paths = {r["path"] for r in results}
        assert result_paths == set(matching_paths)
        assert all(GLOB_NOMATCH_SUFFIX not in r["path"] for r in results)

