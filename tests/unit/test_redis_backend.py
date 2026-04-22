from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import deepagents_backends
from deepagents_backends import RedisBackend


@pytest.mark.unit
class TestRedisBackendUnit:
    @pytest.fixture
    def backend(self, redis_config_unit):
        with patch("deepagents_backends.redis.from_url") as from_url:
            client = MagicMock()
            client.get = AsyncMock()
            client.set = AsyncMock()
            client.exists = AsyncMock()
            client.sadd = AsyncMock()
            client.smembers = AsyncMock(return_value=set())
            client.mget = AsyncMock(return_value=[])
            client.delete = AsyncMock()
            client.aclose = AsyncMock()
            from_url.return_value = client
            backend = RedisBackend(redis_config_unit)
            yield backend, client

    async def test_aread_success(self, backend):
        backend_obj, client = backend
        client.get.return_value = b'{"content": ["line1", "line2"]}'

        result = await backend_obj.aread("test.txt")

        assert "1\tline1" in result
        assert "2\tline2" in result

    async def test_awrite_success(self, backend):
        backend_obj, client = backend
        client.exists.return_value = 0

        result = await backend_obj.awrite("new.txt", "content")

        assert result.error is None
        assert result.path == "new.txt"
        client.set.assert_awaited()
        client.sadd.assert_awaited()

    async def test_awrite_already_exists(self, backend):
        backend_obj, client = backend
        client.exists.return_value = 1

        result = await backend_obj.awrite("exists.txt", "content")

        assert result.error is not None
        assert "already exists" in result.error

    async def test_als_info_collapses_nested_entries(self, backend):
        backend_obj, _client = backend
        backend_obj._list_paths = AsyncMock(
            return_value=[
                ("/file1.txt", 1, None),
                ("/dir/file2.txt", 1, None),
            ]
        )

        results = await backend_obj.als_info("/")

        assert {item["path"] for item in results} == {"/file1.txt", "/dir/"}

    async def test_agrep_raw_filters_by_glob(self, backend):
        backend_obj, _client = backend
        backend_obj._list_paths = AsyncMock(
            return_value=[("/search/match.py", 1, None), ("/search/skip.txt", 1, None)]
        )
        backend_obj._get_file_data = AsyncMock(
            side_effect=[{"content": ["needle"]}, {"content": ["needle"]}]
        )

        result = await backend_obj.agrep_raw("needle", "/search", "*.py")

        assert result == [{"path": "/search/match.py", "line": 1, "text": "needle"}]

    async def test_aglob_info_matches_relative_pattern(self, backend):
        backend_obj, _client = backend
        backend_obj._list_paths = AsyncMock(
            return_value=[("/src/main.py", 1, None), ("/src/readme.txt", 1, None)]
        )

        result = await backend_obj.aglob_info("*.py", "/src")

        assert result == [{"path": "/src/main.py", "is_dir": False, "size": 1, "modified_at": None}]

    async def test_upload_and_download_files(self, backend):
        backend_obj, client = backend
        client.exists.return_value = 0
        client.get.side_effect = [b'{"content": ["payload"]}']

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
        backend_obj, _client = backend
        sentinel = object()

        with patch.object(deepagents_backends, "run_async_safely", return_value=sentinel) as mock_run:
            result = getattr(backend_obj, method_name)(*args)

        assert result is sentinel
        coroutine = mock_run.call_args.args[0]
        try:
            assert coroutine.cr_code.co_name == expected_coroutine_name
        finally:
            coroutine.close()
