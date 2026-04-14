import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
        mock_cur.fetchall.return_value = self._make_list_rows(large_flat_paths)

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
        mock_cur.fetchall.return_value = self._make_list_rows(large_nested_paths)

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

        # _list_paths uses fetchall; _get_file_data uses fetchone.
        mock_cur.fetchall.return_value = self._make_list_rows(all_paths)

        matching_storage = {p.lstrip("/") for p in matching_paths}
        last_params: list = [None]

        async def tracked_execute(query, params=None):
            last_params[0] = params

        mock_cur.execute = AsyncMock(side_effect=tracked_execute)

        def fetchone_by_path():
            params = last_params[0]
            storage_path = params[0] if params else None
            if storage_path in matching_storage:
                return [json.dumps({"content": [GREP_MATCH_LINE]}), None, None]
            return [json.dumps({"content": [GREP_NOMATCH_LINE]}), None, None]

        mock_cur.fetchone.side_effect = fetchone_by_path

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

