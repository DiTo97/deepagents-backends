"""
Example usage of DeepAgents Remote Backends.

This module demonstrates how to use S3Backend and PostgresBackend
with DeepAgents for distributed file storage.
"""

import asyncio

from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config


async def s3_example() -> None:
    """Example: Using S3Backend with MinIO or AWS S3."""
    print("=" * 60)
    print("S3 Backend Example")
    print("=" * 60)

    # Configure for MinIO (local S3-compatible storage)
    config = S3Config(
        bucket="deepagents-files",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",  # MinIO endpoint
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )

    # For AWS S3, use:
    # config = S3Config(
    #     bucket="my-deepagents-bucket",
    #     prefix="production/agent-files",
    #     region="us-west-2",
    #     # Credentials from environment or IAM role
    # )

    backend = S3Backend(config)

    # Write a file
    result = await backend.awrite("/src/hello.py", 'print("Hello, World!")')
    print(f"Write result: {result}")

    # Read the file
    content = await backend.aread("/src/hello.py")
    print(f"Read content:\n{content}")

    # Edit the file
    edit_result = await backend.aedit(
        "/src/hello.py",
        "Hello, World!",
        "Hello from S3!",
    )
    print(f"Edit result: {edit_result}")

    # List files
    files = await backend.als_info("/src")
    print(f"Files in /src: {files}")

    # Search with grep
    matches = await backend.agrep_raw("Hello", "/src", "*.py")
    print(f"Grep matches: {matches}")

    # Upload raw bytes
    responses = await backend.aupload_files([
        ("/data/config.json", b'{"version": 1}'),
        ("/data/readme.txt", b"This is a readme file."),
    ])
    print(f"Upload responses: {responses}")

    # Download files
    downloads = await backend.adownload_files(["/data/config.json"])
    print(f"Download responses: {downloads}")


async def postgres_example() -> None:
    """Example: Using PostgresBackend with connection pooling."""
    print("\n" + "=" * 60)
    print("PostgreSQL Backend Example")
    print("=" * 60)

    # Configure PostgreSQL connection
    config = PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents",
        user="postgres",
        password="postgres",
        table="agent_files",
        min_pool_size=2,
        max_pool_size=10,
    )

    backend = PostgresBackend(config)

    try:
        # Initialize the database schema
        await backend.initialize()
        print("Database initialized successfully")

        # Write a file
        result = await backend.awrite(
            "/project/main.py",
            """def main():
    print("Hello from PostgreSQL!")

if __name__ == "__main__":
    main()
""",
        )
        print(f"Write result: {result}")

        # Read the file
        content = await backend.aread("/project/main.py")
        print(f"Read content:\n{content}")

        # Edit the file
        edit_result = await backend.aedit(
            "/project/main.py",
            "Hello from PostgreSQL!",
            "Hello from DeepAgents!",
        )
        print(f"Edit result: {edit_result}")

        # List files
        files = await backend.als_info("/project")
        print(f"Files in /project: {files}")

        # Glob search
        py_files = await backend.aglob_info("*.py", "/project")
        print(f"Python files: {py_files}")

        # Grep search
        matches = await backend.agrep_raw("def ", "/project")
        print(f"Grep matches for 'def ': {matches}")

        # Batch upload
        responses = await backend.aupload_files([
            ("/project/utils.py", b"# Utility functions\n"),
            ("/project/tests/test_main.py", b"# Tests\n"),
        ])
        print(f"Upload responses: {responses}")

    finally:
        # Always close the connection pool
        await backend.close()
        print("Connection pool closed")


async def deepagents_integration_example() -> None:
    """Example: Integrating with DeepAgents."""
    print("\n" + "=" * 60)
    print("DeepAgents Integration Example")
    print("=" * 60)

    print("""
# Using S3Backend with DeepAgents:

from deepagents import DeepAgent
from main import S3Backend, S3Config

# Create S3 backend
s3_config = S3Config(
    bucket="my-agents",
    endpoint_url="http://minio:9000",
    access_key_id="minioadmin",
    secret_access_key="minioadmin",
)
backend = S3Backend(s3_config)

# Create agent with S3 backend
agent = DeepAgent(
    model="claude-3-5-sonnet-20241022",
    backend=backend,
)

# Run the agent - files will be stored in S3
result = agent.run("Create a Python project structure")


# Using PostgresBackend with DeepAgents:

from main import PostgresBackend, PostgresConfig

# Create PostgreSQL backend
pg_config = PostgresConfig(
    host="postgres.example.com",
    database="agents_db",
    user="agent_user",
    password="secure_password",
)
pg_backend = PostgresBackend(pg_config)

# Initialize schema (run once)
await pg_backend.initialize()

# Create agent with PostgreSQL backend
agent = DeepAgent(
    model="gpt-4o",
    backend=pg_backend,
)

# Run the agent - files will be stored in PostgreSQL
result = agent.run("Analyze the codebase and create tests")

# Don't forget to close the pool when done
await pg_backend.close()
""")


async def main() -> None:
    """Run all examples."""
    print("DeepAgents Remote Backends - Examples")
    print("=" * 60)
    print()
    print("Note: These examples require running S3/MinIO and PostgreSQL.")
    print("Uncomment the example you want to run.\n")

    # Uncomment to run examples (requires running services):
    # await s3_example()
    # await postgres_example()

    # This example just prints usage patterns
    await deepagents_integration_example()


if __name__ == "__main__":
    asyncio.run(main())
