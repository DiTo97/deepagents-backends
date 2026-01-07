# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "deepagents",
#     "deepagents-backends",
# ]
# ///
"""
PostgreSQL Backend Deep Agent Example

This example shows how to create a DeepAgent that stores all its files
in PostgreSQL. This enables:
- ACID-compliant file storage with full transaction support
- Efficient querying with database indexes
- Integration with existing PostgreSQL infrastructure
- Connection pooling for high-performance multi-agent scenarios

Prerequisites:
- PostgreSQL running (docker-compose up -d for local PostgreSQL)

Usage:
    uv run examples/postgres_deep_agent.py
"""

import asyncio
import os
from contextlib import asynccontextmanager

from deepagents import create_deep_agent
from deepagents_backends import PostgresBackend, PostgresConfig


def create_postgres_config_for_local() -> PostgresConfig:
    """Create a PostgreSQL config for local development."""
    return PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents_test",
        user="postgres",
        password="postgres",
        table="agent_files",
        min_pool_size=2,
        max_pool_size=10,
    )


def create_postgres_config_for_production() -> PostgresConfig:
    """Create a PostgreSQL config for production use."""
    return PostgresConfig(
        host=os.environ.get("POSTGRES_HOST", "postgres.example.com"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "deepagents"),
        user=os.environ.get("POSTGRES_USER", "agent_user"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        table="agent_files",
        min_pool_size=5,
        max_pool_size=20,
        sslmode="require",  # Always use SSL in production
    )


@asynccontextmanager
async def postgres_backend(config: PostgresConfig):
    """Context manager for PostgresBackend with proper lifecycle management."""
    backend = PostgresBackend(config)
    try:
        # Initialize creates the table and indexes if they don't exist
        await backend.initialize()
        yield backend
    finally:
        # Always close the connection pool
        await backend.close()


async def main():
    """Run a DeepAgent with PostgreSQL backend for persistent file storage."""

    config = create_postgres_config_for_local()

    async with postgres_backend(config) as backend:
        # Create the deep agent with PostgreSQL backend
        # All file operations will use PostgreSQL with connection pooling
        agent = create_deep_agent(
            backend=backend,
            system_prompt="""You are a data analysis assistant.

When the user asks you to analyze data or create reports:
1. Plan the analysis using todos
2. Create well-documented Python scripts
3. Save results and visualizations to files
4. Generate markdown reports with findings

Files you create will be stored in PostgreSQL and persist across sessions.""",
        )

        print("Running DeepAgent with PostgreSQL backend...")
        print("=" * 60)

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": """Create a data analysis project structure with:
1. A main analysis script that loads CSV data
2. A utility module for common data operations
3. A README explaining the project

Store all files under /data_analysis/""",
                    }
                ]
            }
        )

        # Print the final response
        for message in result["messages"]:
            if hasattr(message, "content") and message.content:
                print(f"\n{message.type}: {message.content[:500]}...")

        print("\n" + "=" * 60)
        print("Files are now stored in PostgreSQL and will persist!")


async def multi_agent_example():
    """Example: Multiple agents sharing the same PostgreSQL backend.

    This demonstrates how PostgreSQL connection pooling enables
    efficient multi-agent workflows with shared file access.
    """
    config = create_postgres_config_for_local()

    async with postgres_backend(config) as backend:
        # Create specialized agents that share the same backend
        researcher = create_deep_agent(
            backend=backend,
            system_prompt="""You are a research agent.
Your job is to research topics and save findings to /research/.""",
        )

        writer = create_deep_agent(
            backend=backend,
            system_prompt="""You are a technical writer.
Read research from /research/ and create polished documentation in /docs/.""",
        )

        print("Multi-Agent PostgreSQL Example")
        print("=" * 60)

        # Agent 1: Research phase
        print("\n[Researcher Agent] Conducting research...")
        await researcher.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Research best practices for Python async programming and save notes to /research/async_python.md",
                    }
                ]
            }
        )

        # Agent 2: Writing phase (reads research agent's output)
        print("\n[Writer Agent] Creating documentation...")
        await writer.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Read the research in /research/ and create a polished guide at /docs/async_guide.md",
                    }
                ]
            }
        )

        print("\n" + "=" * 60)
        print("Multi-agent workflow complete! Both agents shared PostgreSQL storage.")


async def with_subagents_example():
    """Example: Using sub-agents with PostgreSQL backend."""
    config = create_postgres_config_for_local()

    async with postgres_backend(config) as backend:
        # Define specialized sub-agents
        code_reviewer = {
            "name": "code-reviewer",
            "description": "Reviews code for quality and suggests improvements",
            "system_prompt": """You are an expert code reviewer.
Analyze code files and provide detailed feedback on:
- Code quality and readability
- Potential bugs or issues
- Performance considerations
- Best practices""",
        }

        test_writer = {
            "name": "test-writer",
            "description": "Creates comprehensive test suites",
            "system_prompt": """You are a testing expert.
Create thorough test suites with:
- Unit tests for all functions
- Edge case coverage
- Clear test documentation""",
        }

        # Main agent can delegate to sub-agents
        agent = create_deep_agent(
            backend=backend,
            subagents=[code_reviewer, test_writer],
            system_prompt="""You are a senior developer who coordinates code quality.

For code quality tasks:
1. Use the code-reviewer sub-agent to analyze existing code
2. Use the test-writer sub-agent to create tests
3. Synthesize feedback and create improvement plans

All files are stored in PostgreSQL for persistence.""",
        )

        print("Sub-agents with PostgreSQL Example")
        print("=" * 60)

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": """Review the code in /data_analysis/ (if it exists) and:
1. Delegate to code-reviewer for quality analysis
2. Delegate to test-writer to create tests
3. Summarize findings in /reviews/analysis_review.md""",
                    }
                ]
            }
        )

        print("Sub-agent workflow complete!")


async def human_in_the_loop_example():
    """Example: PostgreSQL backend with human-in-the-loop approval."""
    from langgraph.checkpoint.memory import MemorySaver

    config = create_postgres_config_for_local()

    async with postgres_backend(config) as backend:
        # Configure tools that require human approval
        agent = create_deep_agent(
            backend=backend,
            interrupt_on={
                # File writes require approval
                "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
                "edit_file": {"allowed_decisions": ["approve", "edit", "reject"]},
            },
            system_prompt="You are a careful assistant that asks for approval before writing files.",
        )

        # Note: In production, you'd use a persistent checkpointer
        # and handle the interrupt/resume flow
        print("Human-in-the-Loop with PostgreSQL Example")
        print("=" * 60)
        print("This agent will pause for approval before writing files.")
        print("See LangGraph documentation for full HITL implementation.")


if __name__ == "__main__":
    # Run the main example
    asyncio.run(main())

    # Uncomment to run other examples:
    # asyncio.run(multi_agent_example())
    # asyncio.run(with_subagents_example())
    # asyncio.run(human_in_the_loop_example())
