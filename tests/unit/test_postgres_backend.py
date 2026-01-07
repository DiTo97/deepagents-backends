import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from deepagents_backends import PostgresBackend


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
