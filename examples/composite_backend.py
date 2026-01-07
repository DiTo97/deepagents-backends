# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "deepagents",
#     "deepagents-backends",
# ]
# ///
"""
Composite Backend Example - Hybrid S3 + PostgreSQL Storage

This advanced example shows how to create a DeepAgent with a
CompositeBackend that routes different paths to different storage backends.

Use cases:
- Store large binary files in S3, metadata in PostgreSQL
- Keep sensitive data in PostgreSQL, public assets in S3
- Use ephemeral state for working files, persistent storage for results

Prerequisites:
- Both S3/MinIO and PostgreSQL running (docker-compose up -d)

Usage:
    uv run examples/composite_backend.py
"""

import asyncio
from contextlib import asynccontextmanager

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend
from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config


def create_s3_backend() -> S3Backend:
    """Create S3 backend for large files and assets."""
    config = S3Config(
        bucket="test-bucket",
        prefix="agent-assets",
        endpoint_url="http://localhost:9000",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )
    return S3Backend(config)


def create_postgres_config() -> PostgresConfig:
    """Create PostgreSQL config for structured data."""
    return PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents_test",
        user="postgres",
        password="postgres",
        table="agent_files",
    )


@asynccontextmanager
async def composite_backend():
    """Create a composite backend with multiple storage routes.

    Route configuration:
    - /assets/ → S3 (large files, binary data)
    - /data/ → PostgreSQL (structured data, queries)
    - /memories/ → PostgreSQL (persistent across sessions)
    - Everything else → Ephemeral state (temporary working files)
    """
    s3_backend = create_s3_backend()
    pg_backend = PostgresBackend(create_postgres_config())

    try:
        await pg_backend.initialize()

        # Create composite backend with path-based routing
        backend = CompositeBackend(
            default=StateBackend(),  # Ephemeral for working files
            routes={
                "/assets/": s3_backend,  # Large files go to S3
                "/data/": pg_backend,  # Structured data to PostgreSQL
                "/memories/": pg_backend,  # Long-term memory to PostgreSQL
            },
        )

        yield backend

    finally:
        await pg_backend.close()


async def main():
    """Run a DeepAgent with hybrid S3 + PostgreSQL storage."""

    async with composite_backend() as backend:
        agent = create_deep_agent(
            backend=backend,
            system_prompt="""You are a data processing assistant with hybrid storage.

Storage routing:
- /assets/ → S3 storage for large files, images, binary data
- /data/ → PostgreSQL for structured data and analysis results
- /memories/ → PostgreSQL for persistent notes and preferences
- Other paths → Ephemeral working space (temporary files)

When processing data:
1. Store input/output files in /assets/ for durability
2. Save analysis results to /data/ for querying
3. Keep personal notes in /memories/ for future reference
4. Use temporary paths for intermediate processing""",
        )

        print("Running DeepAgent with Composite Backend")
        print("=" * 60)
        print("Routes:")
        print("  /assets/   → S3 (large files)")
        print("  /data/     → PostgreSQL (structured data)")
        print("  /memories/ → PostgreSQL (persistent memory)")
        print("  /other/    → Ephemeral state")
        print("=" * 60)

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": """Set up a project with hybrid storage:

1. Create /assets/sample_data.csv with some sample data
2. Create /data/analysis_config.json with analysis parameters
3. Save a note to /memories/project_notes.md about this project
4. Create /scratch/temp_notes.txt as a working file

Then explain where each file is stored and why.""",
                    }
                ]
            }
        )

        for message in result["messages"]:
            if hasattr(message, "content") and message.content:
                print(f"\n{message.type}: {message.content[:800]}...")


async def long_term_memory_example():
    """Example: Using composite backend for agent memory across sessions."""

    async with composite_backend() as backend:
        # First session - agent learns user preferences
        agent = create_deep_agent(
            backend=backend,
            system_prompt="""You are a personalized assistant with long-term memory.

Store user preferences and learned information in /memories/.
This data persists across conversations.

When you learn something about the user, save it to:
- /memories/preferences.md for user preferences
- /memories/context.md for important context
- /memories/history.md for conversation highlights""",
        )

        print("Long-term Memory Example")
        print("=" * 60)

        # Session 1: Learn preferences
        print("\n[Session 1] Learning user preferences...")
        await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "I prefer Python over JavaScript, and I like detailed explanations. Remember this for our future conversations.",
                    }
                ]
            }
        )

        # Session 2: Use remembered preferences
        print("\n[Session 2] Using remembered preferences...")
        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Read my preferences from /memories/ and recommend a good framework for building web APIs.",
                    }
                ]
            }
        )

        print("\n" + "=" * 60)
        print("Memory persists in PostgreSQL across sessions!")


if __name__ == "__main__":
    asyncio.run(main())

    # Uncomment for memory example:
    # asyncio.run(long_term_memory_example())
