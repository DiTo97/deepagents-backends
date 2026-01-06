import pytest
import asyncio

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
