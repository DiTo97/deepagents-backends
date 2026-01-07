"""
Pytest configuration and fixtures for deepagents-backends tests.
"""

import asyncio
import os
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest

from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config

# Windows requires SelectorEventLoop for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config: Any) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (require Docker)")
    config.addinivalue_line("markers", "s3: Tests requiring S3/MinIO")
    config.addinivalue_line("markers", "postgres: Tests requiring PostgreSQL")


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Auto-mark tests based on their location."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# =============================================================================
# Docker Service Fixtures (for pytest-docker)
# =============================================================================


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    """Path to docker-compose.yml."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker-compose.yml")


@pytest.fixture(scope="session")
def docker_compose_project_name() -> str:
    """
    Fixed project name for test isolation.
    
    Using a fixed name prevents orphaned containers when tests are interrupted
    (e.g., debugging in IDE). The docker_setup fixture will clean up any
    existing containers with this name before starting fresh.
    """
    return "deepagents-backends-test"


@pytest.fixture(scope="session")
def docker_setup() -> list[str]:
    """
    Docker Compose commands to run before tests.
    
    - 'down -v' ensures clean state (removes any leftover containers/volumes)
    - 'up --build --wait' starts services and waits for health checks
    
    The --wait flag respects the healthcheck configurations in docker-compose.yml,
    so services will be ready when tests start.
    """
    return ["down -v", "up --build --wait"]


@pytest.fixture(scope="session")
def docker_cleanup() -> list[str]:
    """
    Docker Compose commands to run after tests.
    
    Removes containers and volumes to ensure clean state for next run.
    """
    return ["down -v"]


# =============================================================================
# S3/MinIO Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def minio_url(docker_services: Any, docker_ip: str) -> str:
    """
    Get MinIO endpoint URL after service is ready.
    
    The docker_services fixture (from pytest-docker) ensures containers are
    started via docker-compose. We wait for MinIO to accept connections and
    create the test bucket.
    """
    port = docker_services.port_for("minio", 9000)
    url = f"http://{docker_ip}:{port}"
    
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_minio_ready(url),
    )
    return url


def _check_minio_ready(endpoint_url: str) -> bool:
    """Check if MinIO is ready and create test bucket."""
    try:
        # Create the test bucket using aioboto3
        async def create_bucket():
            import aioboto3
            session = aioboto3.Session(
                aws_access_key_id="minioadmin",
                aws_secret_access_key="minioadmin",
            )
            async with session.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name="us-east-1",
                use_ssl=False,
            ) as s3:
                try:
                    await s3.create_bucket(Bucket="test-bucket")
                except s3.exceptions.BucketAlreadyOwnedByYou:
                    pass
                except s3.exceptions.BucketAlreadyExists:
                    pass
        
        asyncio.run(create_bucket())
        return True
    except Exception:
        return False


@pytest.fixture
def s3_config(minio_url: str) -> S3Config:
    """S3Config for MinIO test instance."""
    return S3Config(
        bucket="test-bucket",
        prefix="test-run",
        endpoint_url=minio_url,
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
        region="us-east-1",
    )


@pytest.fixture
async def s3_backend(s3_config: S3Config) -> AsyncGenerator[S3Backend, None]:
    """S3Backend instance for testing."""
    backend = S3Backend(s3_config)
    yield backend


# =============================================================================
# PostgreSQL Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def postgres_url(docker_services: Any, docker_ip: str) -> tuple[str, int]:
    """
    Get PostgreSQL connection info after service is ready.
    
    Returns a tuple of (host, port) for connecting to PostgreSQL.
    """
    port = docker_services.port_for("postgres", 5432)
    
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_postgres_ready(docker_ip, port),
    )
    return (docker_ip, port)


def _check_postgres_ready(host: str, port: int) -> bool:
    """Check if PostgreSQL is ready."""
    import socket
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


@pytest.fixture
def postgres_config(postgres_url: tuple[str, int]) -> PostgresConfig:
    """PostgresConfig for test instance."""
    host, port = postgres_url
    return PostgresConfig(
        host=host,
        port=port,
        database="deepagents_test",
        user="postgres",
        password="postgres",
        table="test_files",
        schema="public",
        min_pool_size=2,
        max_pool_size=5,
    )


@pytest.fixture
async def postgres_backend(
    postgres_config: PostgresConfig,
) -> AsyncGenerator[PostgresBackend, None]:
    """PostgresBackend instance for testing."""
    backend = PostgresBackend(postgres_config)
    await backend.initialize()
    yield backend
    # Cleanup: drop table and close pool
    pool = await backend._ensure_pool()
    async with pool.connection() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {backend._table}")
        await conn.commit()
    await backend.close()


# =============================================================================
# Unit Test Fixtures (no external dependencies)
# =============================================================================


@pytest.fixture
def s3_config_unit() -> S3Config:
    """S3Config for unit tests (won't connect)."""
    return S3Config(
        bucket="unit-test-bucket",
        prefix="unit-test",
        endpoint_url="http://localhost:9999",
        access_key_id="test",
        secret_access_key="test",
        use_ssl=False,
    )


@pytest.fixture
def postgres_config_unit() -> PostgresConfig:
    """PostgresConfig for unit tests (won't connect)."""
    return PostgresConfig(
        host="localhost",
        port=54321,
        database="unit_test",
        user="test",
        password="test",
        table="unit_files",
    )
