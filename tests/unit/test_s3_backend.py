import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from deepagents_backends import S3Backend


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
        assert "1 | line1" in result
        assert "2 | line2" in result
        
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
        
        # Mock pagination
        page1 = {
            "Contents": [
                {"Key": "unit-test/file1.txt", "Size": 100, "LastModified": MagicMock()},
                {"Key": "unit-test/dir/file2.txt", "Size": 200, "LastModified": MagicMock()},
            ]
        }
        
        # Setup async iterator for paginator
        async def async_pages(*args, **kwargs):
            yield page1

        paginator.paginate.return_value = async_pages()

        # Mock datetime.isoformat for LastModified
        page1["Contents"][0]["LastModified"].isoformat.return_value = "2023-01-01T00:00:00Z"
        page1["Contents"][1]["LastModified"].isoformat.return_value = "2023-01-01T00:00:00Z"

        results = await backend.als_info("/")
        
        assert len(results) == 2
        # Should see file1.txt and dir/
        paths = {r["path"] for r in results}
        assert "/file1.txt" in paths
        assert "/dir/" in paths
