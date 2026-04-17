import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import deepagents_backends
from deepagents_backends import AzureBlobBackend


@pytest.mark.unit
class TestAzureBlobBackendUnit:
    @pytest.fixture
    def backend(self, azure_blob_config_unit):
        with patch("deepagents_backends.BlobServiceClient.from_connection_string") as factory:
            service = MagicMock()
            service.close = AsyncMock()
            container = MagicMock()
            service.get_container_client.return_value = container
            factory.return_value = service
            backend = AzureBlobBackend(azure_blob_config_unit)
            yield backend, service, container

    async def test_aread_success(self, backend):
        backend_obj, _service, container = backend
        blob = MagicMock()
        downloader = MagicMock()
        downloader.readall = AsyncMock(
            return_value=json.dumps({"content": ["line1", "line2"]}).encode("utf-8")
        )
        blob.download_blob = AsyncMock(return_value=downloader)
        container.get_blob_client.return_value = blob

        result = await backend_obj.aread("test.txt")

        assert "1\tline1" in result
        assert "2\tline2" in result
        container.get_blob_client.assert_called_once_with("unit-test/test.txt")

    async def test_awrite_success(self, backend):
        backend_obj, _service, container = backend
        blob = MagicMock()
        blob.exists = AsyncMock(return_value=False)
        blob.upload_blob = AsyncMock()
        container.get_blob_client.return_value = blob

        result = await backend_obj.awrite("new.txt", "content")

        assert result.error is None
        assert result.path == "new.txt"
        blob.upload_blob.assert_awaited()

    async def test_awrite_already_exists(self, backend):
        backend_obj, _service, container = backend
        blob = MagicMock()
        blob.exists = AsyncMock(return_value=True)
        container.get_blob_client.return_value = blob

        result = await backend_obj.awrite("exists.txt", "content")

        assert result.error is not None
        assert "already exists" in result.error

    async def test_als_info_collapses_nested_entries(self, backend):
        backend_obj, _service, _container = backend
        backend_obj._list_blobs = AsyncMock(
            return_value=[
                ("/file1.txt", 10, "2024-01-01T00:00:00+00:00"),
                ("/dir/file2.txt", 10, "2024-01-01T00:00:00+00:00"),
            ]
        )

        results = await backend_obj.als_info("/")

        assert {item["path"] for item in results} == {"/file1.txt", "/dir/"}

    async def test_agrep_raw_filters_by_glob(self, backend):
        backend_obj, _service, _container = backend
        backend_obj._list_blobs = AsyncMock(
            return_value=[("/search/match.py", 1, None), ("/search/skip.txt", 1, None)]
        )
        backend_obj._get_file_data = AsyncMock(
            side_effect=[{"content": ["needle"]}, {"content": ["needle"]}]
        )

        result = await backend_obj.agrep_raw("needle", "/search", "*.py")

        assert result == [{"path": "/search/match.py", "line": 1, "text": "needle"}]

    async def test_aglob_info_matches_relative_pattern(self, backend):
        backend_obj, _service, _container = backend
        backend_obj._list_blobs = AsyncMock(
            return_value=[("/src/main.py", 1, None), ("/src/readme.txt", 1, None)]
        )

        result = await backend_obj.aglob_info("*.py", "/src")

        assert result == [{"path": "/src/main.py", "is_dir": False, "size": 1, "modified_at": None}]

    async def test_upload_and_download_files(self, backend):
        backend_obj, _service, container = backend
        blob = MagicMock()
        blob.upload_blob = AsyncMock()
        downloader = MagicMock()
        downloader.readall = AsyncMock(return_value=b"payload")
        blob.download_blob = AsyncMock(return_value=downloader)
        container.get_blob_client.return_value = blob

        upload_responses = await backend_obj.aupload_files([("file.bin", b"payload")])
        download_responses = await backend_obj.adownload_files(["file.bin"])

        assert upload_responses[0].error is None
        assert download_responses[0].content == b"payload"

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
        backend_obj, _service, _container = backend
        sentinel = object()

        with patch.object(deepagents_backends, "run_async_safely", return_value=sentinel) as mock_run:
            result = getattr(backend_obj, method_name)(*args)

        assert result is sentinel
        coroutine = mock_run.call_args.args[0]
        try:
            assert coroutine.cr_code.co_name == expected_coroutine_name
        finally:
            coroutine.close()
