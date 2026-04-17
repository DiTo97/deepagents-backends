import pytest


@pytest.mark.integration
@pytest.mark.gcs
class TestGCSBackendIntegration:
    async def test_full_lifecycle(self, gcs_backend):
        write_res = await gcs_backend.awrite("hello.txt", "Hello GCS\nLine 2")
        assert write_res.error is None
        assert write_res.path == "hello.txt"

        read_res = await gcs_backend.aread("hello.txt")
        assert "Hello GCS" in read_res
        assert "Line 2" in read_res

        ls_res = await gcs_backend.als_info("/")
        assert any(f["path"] == "/hello.txt" for f in ls_res)

        edit_res = await gcs_backend.aedit("hello.txt", "GCS", "Storage")
        assert edit_res.error is None
        assert edit_res.occurrences == 1

        read_res_2 = await gcs_backend.aread("hello.txt")
        assert "Hello Storage" in read_res_2

    async def test_grep(self, gcs_backend):
        await gcs_backend.awrite("grep_me.txt", "match this pattern\ndon't match this")

        matches = await gcs_backend.agrep_raw("pattern")
        assert len(matches) == 1
        assert matches[0]["text"] == "match this pattern"
        assert matches[0]["line"] == 1

    async def test_glob(self, gcs_backend):
        await gcs_backend.awrite("src/main.py", "print('hello')")
        await gcs_backend.awrite("src/utils.py", "def util(): pass")
        await gcs_backend.awrite("README.md", "# Readme")

        results = await gcs_backend.aglob_info("*.py", "/src")
        assert len(results) == 2
        paths = sorted([r["path"] for r in results])
        assert paths == ["/src/main.py", "/src/utils.py"]
