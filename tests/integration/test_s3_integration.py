import pytest
import asyncio

@pytest.mark.integration
@pytest.mark.s3
class TestS3BackendIntegration:
    async def test_full_lifecycle(self, s3_backend):
        # 1. Write
        write_res = await s3_backend.awrite("hello.txt", "Hello World\nLine 2")
        assert write_res.error is None
        assert write_res.path == "hello.txt"

        # 2. Read
        read_res = await s3_backend.aread("hello.txt")
        assert "Hello World" in read_res
        assert "Line 2" in read_res

        # 3. List
        ls_res = await s3_backend.als_info("/")
        assert any(f["path"] == "/hello.txt" for f in ls_res)

        # 4. Edit
        edit_res = await s3_backend.aedit("hello.txt", "World", "Integration")
        assert edit_res.error is None
        assert edit_res.occurrences == 1
        
        read_res_2 = await s3_backend.aread("hello.txt")
        assert "Hello Integration" in read_res_2

    async def test_grep(self, s3_backend):
        await s3_backend.awrite("grep_me.txt", "match this pattern\ndon't match this")
        
        matches = await s3_backend.agrep_raw("pattern")
        assert len(matches) == 1
        assert matches[0]["text"] == "match this pattern"
        assert matches[0]["line"] == 1

    async def test_glob(self, s3_backend):
        await s3_backend.awrite("src/main.py", "print('hello')")
        await s3_backend.awrite("src/utils.py", "def util(): pass")
        await s3_backend.awrite("README.md", "# Readme")

        results = await s3_backend.aglob_info("*.py", "/src")
        assert len(results) == 2
        paths = sorted([r["path"] for r in results])
        assert paths == ["/src/main.py", "/src/utils.py"]
