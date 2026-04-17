"""
Pytest configuration and fixtures for deepagents-backends tests.
"""

import asyncio
import json
import os
import socket
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from deepagents_backends import (
    AzureBlobBackend,
    AzureBlobConfig,
    GCSBackend,
    GCSConfig,
    MongoDBBackend,
    MongoDBConfig,
    PostgresBackend,
    PostgresConfig,
    RedisBackend,
    RedisConfig,
    S3Backend,
    S3Config,
)
from tests.common.scalability import (
    INTEGRATION_FILES_PER_DIR,
    INTEGRATION_FLAT_FILES,
    INTEGRATION_NESTED_DIRS,
    LARGE_FLAT_FILES,
    LARGE_NESTED_DIRS,
    LARGE_NESTED_FILES_PER_DIR,
    flat_file_paths,
    glob_dataset_paths,
    grep_dataset_paths,
    nested_tree_paths,
)

# Windows requires SelectorEventLoop for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config: Any) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (require Docker)")
    config.addinivalue_line("markers", "s3: Tests requiring S3/MinIO")
    config.addinivalue_line("markers", "postgres: Tests requiring PostgreSQL")
    config.addinivalue_line("markers", "azure: Tests requiring Azure Blob Storage / Azurite")
    config.addinivalue_line("markers", "gcs: Tests requiring Google Cloud Storage / fake-gcs-server")
    config.addinivalue_line("markers", "mongodb: Tests requiring MongoDB")
    config.addinivalue_line("markers", "redis: Tests requiring Redis/Valkey")


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
    """S3Config for MinIO test instance with a unique prefix per test."""
    return S3Config(
        bucket="test-bucket",
        prefix=f"test-run-{uuid.uuid4().hex[:8]}",
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
# Common readiness helpers
# =============================================================================


def _check_tcp_ready(host: str, port: int) -> bool:
    """Check whether a TCP service is accepting connections."""
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


# =============================================================================
# Azure Blob / Azurite Fixtures
# =============================================================================


AZURITE_ACCOUNT_NAME = "devstoreaccount1"
AZURITE_ACCOUNT_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw=="
)


@pytest.fixture(scope="session")
def azure_connection_string(docker_services: Any, docker_ip: str) -> str:
    """Build an Azurite connection string after the blob endpoint is ready."""
    port = docker_services.port_for("azurite", 10000)
    endpoint = f"http://{docker_ip}:{port}/{AZURITE_ACCOUNT_NAME}"

    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_tcp_ready(docker_ip, port),
    )

    return (
        "DefaultEndpointsProtocol=http;"
        f"AccountName={AZURITE_ACCOUNT_NAME};"
        f"AccountKey={AZURITE_ACCOUNT_KEY};"
        f"BlobEndpoint={endpoint};"
    )


@pytest.fixture
async def azure_blob_config(azure_connection_string: str) -> AzureBlobConfig:
    """AzureBlobConfig for Azurite with a unique prefix per test."""
    config = AzureBlobConfig(
        container="test-container",
        prefix=f"test-run-{uuid.uuid4().hex[:8]}",
        connection_string=azure_connection_string,
    )
    backend = AzureBlobBackend(config)
    await backend.ensure_container()
    await backend.close()
    return config


@pytest.fixture
async def azure_blob_backend(
    azure_blob_config: AzureBlobConfig,
) -> AsyncGenerator[AzureBlobBackend, None]:
    """AzureBlobBackend instance for testing."""
    backend = AzureBlobBackend(azure_blob_config)
    yield backend
    await backend.close()


# =============================================================================
# GCS / fake-gcs-server Fixtures
# =============================================================================


def _check_fake_gcs_ready(api_root: str) -> bool:
    """Check whether fake-gcs-server is accepting JSON API requests."""
    try:
        with urllib.request.urlopen(f"{api_root}/storage/v1/b", timeout=1):
            return True
    except Exception:
        return False


def _ensure_fake_gcs_bucket(api_root: str, bucket_name: str) -> None:
    """Create a fake-gcs-server bucket if it does not already exist."""
    request = urllib.request.Request(
        f"{api_root}/storage/v1/b?project=test-project",
        data=json.dumps({"name": bucket_name}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return
        raise


@pytest.fixture(scope="session")
def gcs_api_root(docker_services: Any, docker_ip: str) -> str:
    """Get the fake GCS JSON API root and create the shared test bucket."""
    port = docker_services.port_for("fake-gcs-server", 4443)
    api_root = f"http://{docker_ip}:{port}"

    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_fake_gcs_ready(api_root),
    )
    _ensure_fake_gcs_bucket(api_root, "test-bucket")
    return api_root


@pytest.fixture
def gcs_config(gcs_api_root: str) -> GCSConfig:
    """GCSConfig for fake-gcs-server with a unique prefix per test."""
    return GCSConfig(
        bucket="test-bucket",
        prefix=f"test-run-{uuid.uuid4().hex[:8]}",
        api_root=gcs_api_root,
    )


@pytest.fixture
async def gcs_backend(gcs_config: GCSConfig) -> AsyncGenerator[GCSBackend, None]:
    """GCSBackend instance for testing."""
    backend = GCSBackend(gcs_config)
    yield backend
    await backend.close()


# =============================================================================
# MongoDB Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def mongodb_url(docker_services: Any, docker_ip: str) -> str:
    """Get a MongoDB connection URI after the service is ready."""
    port = docker_services.port_for("mongodb", 27017)

    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_tcp_ready(docker_ip, port),
    )
    return f"mongodb://{docker_ip}:{port}"


@pytest.fixture
def mongodb_config(mongodb_url: str) -> MongoDBConfig:
    """MongoDBConfig for test instance."""
    return MongoDBConfig(
        connection_uri=mongodb_url,
        database="deepagents_test",
        collection=f"test_files_{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture
async def mongodb_backend(
    mongodb_config: MongoDBConfig,
) -> AsyncGenerator[MongoDBBackend, None]:
    """MongoDBBackend instance for testing."""
    backend = MongoDBBackend(mongodb_config)
    await backend.initialize()
    yield backend
    await backend._collection.drop()
    await backend.close()


# =============================================================================
# Redis / Valkey Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def redis_url(docker_services: Any, docker_ip: str) -> str:
    """Get a Redis/Valkey connection URL after the service is ready."""
    port = docker_services.port_for("valkey", 6379)

    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=lambda: _check_tcp_ready(docker_ip, port),
    )
    return f"redis://{docker_ip}:{port}/0"


@pytest.fixture
def redis_config(redis_url: str) -> RedisConfig:
    """RedisConfig for test instance."""
    return RedisConfig(
        url=redis_url,
        prefix=f"test-run-{uuid.uuid4().hex[:8]}",
        namespace=f"test-ns-{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture
async def redis_backend(redis_config: RedisConfig) -> AsyncGenerator[RedisBackend, None]:
    """RedisBackend instance for testing."""
    backend = RedisBackend(redis_config)
    yield backend
    members = await backend._client.smembers(backend._index_key)
    data_keys = []
    for member in members:
        if isinstance(member, bytes):
            member = member.decode("utf-8")
        data_keys.append(f"{backend._namespace}:file:{member}")
    if data_keys:
        await backend._client.delete(*data_keys)
    await backend._client.delete(backend._index_key)
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
def azure_blob_config_unit() -> AzureBlobConfig:
    """AzureBlobConfig for unit tests (won't connect)."""
    return AzureBlobConfig(
        container="unit-test-container",
        prefix="unit-test",
        connection_string=(
            "DefaultEndpointsProtocol=http;"
            f"AccountName={AZURITE_ACCOUNT_NAME};"
            f"AccountKey={AZURITE_ACCOUNT_KEY};"
            f"BlobEndpoint=http://127.0.0.1:10000/{AZURITE_ACCOUNT_NAME};"
        ),
    )


@pytest.fixture
def gcs_config_unit() -> GCSConfig:
    """GCSConfig for unit tests (won't connect)."""
    return GCSConfig(
        bucket="unit-test-bucket",
        prefix="unit-test",
        api_root="http://127.0.0.1:4443",
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


@pytest.fixture
def mongodb_config_unit() -> MongoDBConfig:
    """MongoDBConfig for unit tests (won't connect)."""
    return MongoDBConfig(
        connection_uri="mongodb://localhost:27018",
        database="unit_test",
        collection="unit_files",
        prefix="unit-test",
    )


@pytest.fixture
def redis_config_unit() -> RedisConfig:
    """RedisConfig for unit tests (won't connect)."""
    return RedisConfig(
        url="redis://localhost:6380/0",
        prefix="unit-test",
        namespace="unit-test-ns",
    )


# =============================================================================
# Scalability Fixtures (unit scale — no real I/O)
# =============================================================================


@pytest.fixture
def large_flat_paths() -> list[str]:
    """200 flat file paths under /large_flat (no sub-directories)."""
    return flat_file_paths(root="/large_flat", n=LARGE_FLAT_FILES)


@pytest.fixture
def large_nested_paths() -> list[str]:
    """300 file paths spread across 10 sub-directories under /large_nested."""
    return nested_tree_paths(
        root="/large_nested",
        n_dirs=LARGE_NESTED_DIRS,
        files_per_dir=LARGE_NESTED_FILES_PER_DIR,
    )


@pytest.fixture
def grep_dataset() -> tuple[list[str], list[str]]:
    """(matching_paths, all_paths) for a unit-scale grep scenario (50 / 300)."""
    return grep_dataset_paths(root="/large_grep", n_matching=50)


@pytest.fixture
def glob_dataset() -> tuple[list[str], list[str]]:
    """(matching_paths, all_paths) for a unit-scale glob scenario (40 / 300)."""
    return glob_dataset_paths(root="/large_glob", n_matching=40)


# =============================================================================
# Scalability Fixtures (integration scale — manageable real I/O)
# =============================================================================


@pytest.fixture
def integration_flat_paths() -> list[str]:
    """25 flat file paths for integration-scale ls tests."""
    return flat_file_paths(root="/int_flat", n=INTEGRATION_FLAT_FILES)


@pytest.fixture
def integration_nested_paths() -> list[str]:
    """24 file paths across 3 sub-directories for integration-scale ls tests."""
    return nested_tree_paths(
        root="/int_nested",
        n_dirs=INTEGRATION_NESTED_DIRS,
        files_per_dir=INTEGRATION_FILES_PER_DIR,
    )


@pytest.fixture
def integration_grep_dataset() -> tuple[list[str], list[str]]:
    """(matching, all) for integration-scale grep scenario (5 / 20)."""
    return grep_dataset_paths(root="/int_grep", n_matching=5, n_total=20)


@pytest.fixture
def integration_glob_dataset() -> tuple[list[str], list[str]]:
    """(matching, all) for integration-scale glob scenario (6 / 20)."""
    return glob_dataset_paths(root="/int_glob", n_matching=6, n_total=20)
