import pytest


@pytest.mark.integration
@pytest.mark.azure
class TestAzureBlobBackendIntegration:
    async def test_full_lifecycle(self, azure_blob_backend):
        write_res = await azure_blob_backend.awrite("hello.txt", "Hello Azure\nLine 2")
        assert write_res.error is None
        assert write_res.path == "hello.txt"

        read_res = await azure_blob_backend.aread("hello.txt")
        assert "Hello Azure" in read_res
        assert "Line 2" in read_res

        ls_res = await azure_blob_backend.als_info("/")
        assert any(f["path"] == "/hello.txt" for f in ls_res)

        edit_res = await azure_blob_backend.aedit("hello.txt", "Azure", "Blob")
        assert edit_res.error is None
        assert edit_res.occurrences == 1

        read_res_2 = await azure_blob_backend.aread("hello.txt")
        assert "Hello Blob" in read_res_2

    async def test_grep(self, azure_blob_backend):
        await azure_blob_backend.awrite("grep_me.txt", "match this pattern\ndon't match this")

        matches = await azure_blob_backend.agrep_raw("pattern")
        assert len(matches) == 1
        assert matches[0]["text"] == "match this pattern"
        assert matches[0]["line"] == 1

    async def test_glob(self, azure_blob_backend):
        await azure_blob_backend.awrite("src/main.py", "print('hello')")
        await azure_blob_backend.awrite("src/utils.py", "def util(): pass")
        await azure_blob_backend.awrite("README.md", "# Readme")

        results = await azure_blob_backend.aglob_info("*.py", "/src")
        assert len(results) == 2
        paths = sorted([r["path"] for r in results])
        assert paths == ["/src/main.py", "/src/utils.py"]
