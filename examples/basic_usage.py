# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "deepagents-backends",
# ]
# ///
"""
Basic Backend Operations Example

This module demonstrates the low-level API of S3Backend and PostgresBackend.
For DeepAgent integration examples, see:
- s3_deep_agent.py - Full S3 backend with DeepAgent
- postgres_deep_agent.py - Full PostgreSQL backend with DeepAgent
- composite_backend.py - Hybrid S3 + PostgreSQL storage

These backends implement Deep Agents' BackendProtocol for remote file storage.

Usage:
    uv run examples/basic_usage.py
"""

import asyncio
import uuid

from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config


async def s3_backend_operations() -> None:
    """Demonstrate low-level S3Backend file operations."""
    root = f"/s3-basic-usage-{uuid.uuid4().hex[:8]}"
    source_file = f"{root}/src/hello.py"
    data_dir = f"{root}/data"

    print("=" * 60)
    print("S3 Backend - Low-level Operations")
    print("=" * 60)
    print(f"Workspace root: {root}")

    # Configure for MinIO (local S3-compatible storage)
    config = S3Config(
        bucket="test-bucket",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )

    backend = S3Backend(config)

    # Write a file (fails if exists - use edit for modifications)
    result = await backend.awrite(source_file, 'print("Hello, World!")')
    print(f"Write result: {result}")

    # Read the file (supports offset/limit for pagination)
    content = await backend.aread(source_file)
    print(f"Read content:\n{content}")

    # Edit the file (string replacement)
    edit_result = await backend.aedit(
        source_file,
        "Hello, World!",
        "Hello from S3!",
    )
    print(f"Edit result: {edit_result}")

    # List files in directory
    files = await backend.als_info(f"{root}/src")
    print(f"Files in {root}/src: {files}")

    # Glob pattern matching
    py_files = await backend.aglob_info("**/*.py", root)
    print(f"All Python files under {root}: {py_files}")

    # Grep search with line numbers
    matches = await backend.agrep_raw("Hello", f"{root}/src", "*.py")
    print(f"Grep matches: {matches}")

    # Batch upload raw bytes
    responses = await backend.aupload_files([
        (f"{data_dir}/config.json", b'{"version": 1}'),
        (f"{data_dir}/readme.txt", b"This is a readme file."),
    ])
    print(f"Upload responses: {responses}")

    # Download files as bytes
    downloads = await backend.adownload_files([f"{data_dir}/config.json"])
    print(f"Download responses: {downloads}")


async def postgres_backend_operations() -> None:
    """Demonstrate low-level PostgresBackend file operations."""
    root = f"/postgres-basic-usage-{uuid.uuid4().hex[:8]}"
    source_file = f"{root}/project/main.py"

    print("\n" + "=" * 60)
    print("PostgreSQL Backend - Low-level Operations")
    print("=" * 60)
    print(f"Workspace root: {root}")

    config = PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents_test",
        user="postgres",
        password="postgres",
        table="agent_files",
        min_pool_size=2,
        max_pool_size=10,
    )

    backend = PostgresBackend(config)

    try:
        # Initialize creates table and indexes
        await backend.initialize()
        print("Database initialized successfully")

        # Write a file
        result = await backend.awrite(
            source_file,
            """def main():
    print(\"Hello from PostgreSQL!\")

if __name__ == \"__main__\":
    main()
""",
        )
        print(f"Write result: {result}")

        # Read the file
        content = await backend.aread(source_file)
        print(f"Read content:\n{content}")

        # Edit the file
        edit_result = await backend.aedit(
            source_file,
            "Hello from PostgreSQL!",
            "Hello from Deep Agents!",
        )
        print(f"Edit result: {edit_result}")

        # List files
        files = await backend.als_info(f"{root}/project")
        print(f"Files in {root}/project: {files}")

        # Glob search
        py_files = await backend.aglob_info("**/*.py", root)
        print(f"Python files under {root}: {py_files}")

        # Grep search with line numbers
        matches = await backend.agrep_raw("def ", f"{root}/project")
        print(f"Grep matches for 'def ': {matches}")

        # Batch upload
        responses = await backend.aupload_files([
            (f"{root}/project/utils.py", b"# Utility functions\n"),
            (f"{root}/project/tests/test_main.py", b"# Tests\n"),
        ])
        print(f"Upload responses: {responses}")

    finally:
        # Always close the connection pool
        await backend.close()
        print("Connection pool closed")


async def main() -> None:
    """Run all examples."""
    print("Deep Agents Remote Backends - Low-level API Examples")
    print("=" * 60)
    print()
    print("For DeepAgent integration examples, see:")
    print("  - examples/s3_deep_agent.py")
    print("  - examples/postgres_deep_agent.py")
    print("  - examples/composite_backend.py")
    print()
    print("Prerequisites: docker-compose up -d")
    print()

    await s3_backend_operations()
    await postgres_backend_operations()


if __name__ == "__main__":
    asyncio.run(main())
