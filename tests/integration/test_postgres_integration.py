
import pytest

from tests.common.scalability import (
    GLOB_MATCH_SUFFIX,
    GLOB_NOMATCH_SUFFIX,
    GREP_MATCH_LINE,
    GREP_NOMATCH_LINE,
    INTEGRATION_FLAT_FILES,
    INTEGRATION_NESTED_DIRS,
)

@pytest.mark.integration
@pytest.mark.postgres
class TestPostgresBackendIntegration:
    async def test_full_lifecycle(self, postgres_backend):
        # 1. Write
        write_res = await postgres_backend.awrite("pg_hello.txt", "Hello Postgres\nLine 2")
        assert write_res.error is None
        assert write_res.path == "pg_hello.txt"

        # 2. Read
        read_res = await postgres_backend.aread("pg_hello.txt")
        assert "Hello Postgres" in read_res

        # 3. List
        ls_res = await postgres_backend.als_info("/")
        assert any(f["path"] == "/pg_hello.txt" for f in ls_res)

        # 4. Edit
        edit_res = await postgres_backend.aedit("pg_hello.txt", "Postgres", "SQL")
        assert edit_res.error is None

        read_res_2 = await postgres_backend.aread("pg_hello.txt")
        assert "Hello SQL" in read_res_2

    async def test_grep(self, postgres_backend):
        await postgres_backend.awrite("pg_grep.txt", "match this pattern\ndon't match this")

        matches = await postgres_backend.agrep_raw("pattern")
        assert len(matches) == 1
        assert matches[0]["text"] == "match this pattern"

    async def test_glob(self, postgres_backend):
        await postgres_backend.awrite("src/pg_main.py", "print('hello')")
        await postgres_backend.awrite("src/pg_utils.py", "def util(): pass")

        results = await postgres_backend.aglob_info("*.py", "/src")
        assert len(results) == 2
        paths = sorted([r["path"] for r in results])
        assert paths == ["/src/pg_main.py", "/src/pg_utils.py"]


@pytest.mark.integration
@pytest.mark.postgres
class TestPostgresBackendScalabilityIntegration:
    """Integration-scale correctness tests for large candidate sets.

    These tests write real rows to PostgreSQL and assert the acceptance
    invariants defined in ``tests/scalability.py``.  Optimization PRs must
    not regress these assertions.
    """

    # ── als_info: flat directory ──────────────────────────────────────────────

    async def test_als_info_large_flat_returns_exact_direct_children(
        self, postgres_backend, integration_flat_paths
    ):
        """Invariant 1a: exact direct-child count, no nested entries."""
        for p in integration_flat_paths:
            await postgres_backend.awrite(p.lstrip("/"), "content")

        results = await postgres_backend.als_info("/int_flat")
        assert len(results) == INTEGRATION_FLAT_FILES
        assert all(not r["is_dir"] for r in results)

    # ── als_info: nested tree ─────────────────────────────────────────────────

    async def test_als_info_large_nested_returns_only_direct_subdirs(
        self, postgres_backend, integration_nested_paths
    ):
        """Invariant 1b: nested files are collapsed to their parent dir entries."""
        for p in integration_nested_paths:
            await postgres_backend.awrite(p.lstrip("/"), "content")

        results = await postgres_backend.als_info("/int_nested")
        assert len(results) == INTEGRATION_NESTED_DIRS
        assert all(r["is_dir"] for r in results)

    # ── agrep_raw: large candidate set ───────────────────────────────────────

    async def test_agrep_raw_large_set_no_false_positives_or_negatives(
        self, postgres_backend, integration_grep_dataset
    ):
        """Invariant 2: grep returns exactly the matching files."""
        matching_paths, all_paths = integration_grep_dataset
        matching_set = set(matching_paths)

        for p in all_paths:
            content = GREP_MATCH_LINE if p in matching_set else GREP_NOMATCH_LINE
            await postgres_backend.awrite(p.lstrip("/"), content)

        results = await postgres_backend.agrep_raw(GREP_MATCH_LINE, "/int_grep")
        assert isinstance(results, list)
        assert len(results) == len(matching_paths)
        assert {r["path"] for r in results} == matching_set

    # ── aglob_info: large candidate set ──────────────────────────────────────

    async def test_aglob_info_large_set_exact_pattern_matches(
        self, postgres_backend, integration_glob_dataset
    ):
        """Invariant 3: aglob_info returns exactly the files matching the pattern."""
        matching_paths, all_paths = integration_glob_dataset

        for p in all_paths:
            await postgres_backend.awrite(p.lstrip("/"), "content")

        results = await postgres_backend.aglob_info(f"*{GLOB_MATCH_SUFFIX}", "/int_glob")
        assert len(results) == len(matching_paths)
        assert {r["path"] for r in results} == set(matching_paths)
        assert all(GLOB_NOMATCH_SUFFIX not in r["path"] for r in results)

