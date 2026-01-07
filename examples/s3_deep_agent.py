# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "deepagents",
#     "deepagents-backends",
#     "tavily-python",
# ]
# ///
"""
S3 Backend Deep Agent Example

This example shows how to create a DeepAgent that stores all its files
in S3 or S3-compatible storage (like MinIO). This enables:
- Persistent file storage across agent sessions
- Distributed agent execution with shared file access
- Easy backup and recovery of agent workspaces

Prerequisites:
- S3/MinIO running (docker-compose up -d for local MinIO)

Usage:
    uv run examples/s3_deep_agent.py
"""

import asyncio
import os

from deepagents import create_deep_agent
from deepagents_backends import S3Backend, S3Config


def create_s3_backend_for_minio() -> S3Backend:
    """Create an S3 backend configured for local MinIO development."""
    config = S3Config(
        bucket="test-bucket",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )
    return S3Backend(config)


def create_s3_backend_for_aws() -> S3Backend:
    """Create an S3 backend configured for AWS S3 production use."""
    config = S3Config(
        bucket=os.environ.get("AWS_S3_BUCKET", "my-deepagents-bucket"),
        prefix="production/agent-files",
        region=os.environ.get("AWS_REGION", "us-west-2"),
        # Credentials from environment variables or IAM role
        access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        use_ssl=True,
    )
    return S3Backend(config)


async def main():
    """Run a DeepAgent with S3 backend for persistent file storage."""

    # Create S3 backend (use MinIO for local development)
    backend = create_s3_backend_for_minio()

    # Create the deep agent with S3 backend
    # All file operations (read, write, edit, glob, grep) will use S3
    agent = create_deep_agent(
        backend=backend,
        system_prompt="""You are a Python developer assistant.

When the user asks you to create code:
1. Plan the work using todos
2. Create well-structured Python files
3. Include docstrings and type hints
4. Write tests when appropriate

Files you create will be stored in S3 and persist across sessions.""",
    )

    # Example: Ask the agent to create a project
    print("Running DeepAgent with S3 backend...")
    print("=" * 60)

    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": """Create a simple calculator module with:
1. Functions for add, subtract, multiply, divide
2. Error handling for division by zero
3. A simple test file

Store all files under /calculator/""",
                }
            ]
        }
    )

    # Print the final response
    for message in result["messages"]:
        if hasattr(message, "content") and message.content:
            print(f"\n{message.type}: {message.content[:500]}...")

    print("\n" + "=" * 60)
    print("Files are now stored in S3 and will persist!")
    print("You can run this agent again to read/modify the files.")


async def streaming_example():
    """Example showing streaming with S3 backend."""
    backend = create_s3_backend_for_minio()

    agent = create_deep_agent(
        backend=backend,
        system_prompt="You are a helpful coding assistant. Store files in S3.",
    )

    print("Streaming DeepAgent with S3 backend...")
    print("=" * 60)

    async for chunk in agent.astream(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Read any existing files in /calculator/ and summarize what's there. If nothing exists, say so.",
                }
            ]
        }
    ):
        # Print streamed messages
        if "messages" in chunk:
            msg = chunk["messages"][-1]
            if hasattr(msg, "content") and msg.content:
                print(msg.content, end="", flush=True)

    print("\n" + "=" * 60)


async def with_custom_tools():
    """Example: S3 backend with custom tools."""
    from tavily import TavilyClient

    backend = create_s3_backend_for_minio()

    # Add web search capability (requires TAVILY_API_KEY)
    tavily_api_key = os.environ.get("TAVILY_API_KEY")

    tools = []
    if tavily_api_key:
        tavily_client = TavilyClient(api_key=tavily_api_key)

        def internet_search(query: str, max_results: int = 5):
            """Search the web for information."""
            return tavily_client.search(query, max_results=max_results)

        tools.append(internet_search)

    agent = create_deep_agent(
        backend=backend,
        tools=tools,
        system_prompt="""You are a research assistant.

Use web search to find information, then save your research as
well-organized markdown files in S3 for future reference.""",
    )

    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Research the latest Python 3.12 features and save a summary to /research/python312.md",
                }
            ]
        }
    )

    print("Research complete! Files saved to S3.")


if __name__ == "__main__":
    # Run the main example
    asyncio.run(main())

    # Uncomment to run other examples:
    # asyncio.run(streaming_example())
    # asyncio.run(with_custom_tools())
