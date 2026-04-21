from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aioboto3
from deepagents.backends import FilesystemBackend

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

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmark"
DEFAULT_RESULTS_PATH = BENCHMARK_DIR / "results" / "latest.json"
DEFAULT_README_PATH = BENCHMARK_DIR / "README.md"
DOCKER_COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

MINIO_BUCKET = "benchmark-bucket"
MINIO_ENDPOINT = "http://127.0.0.1:9000"
POSTGRES_HOST = "127.0.0.1"
POSTGRES_PORT = 5432
POSTGRES_DATABASE = "deepagents_test"
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "postgres"
AZURITE_ACCOUNT_NAME = "devstoreaccount1"
AZURITE_ACCOUNT_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw=="
)
AZURE_BLOB_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;"
    f"AccountName={AZURITE_ACCOUNT_NAME};"
    f"AccountKey={AZURITE_ACCOUNT_KEY};"
    f"BlobEndpoint=http://127.0.0.1:10000/{AZURITE_ACCOUNT_NAME};"
)
AZURE_CONTAINER = "benchmark-container"
GCS_API_ROOT = "http://127.0.0.1:4443"
GCS_BUCKET = "benchmark-bucket"
MONGODB_URI = "mongodb://127.0.0.1:27017"
MONGODB_DATABASE = "deepagents_benchmark"
REDIS_URL = "redis://127.0.0.1:6379/0"
WARMUP_RUNS = 1
MEASURED_RUNS = 3

SEARCH_NEEDLE = "SEARCH_HIT_TOKEN_7qK"
EDIT_OLD = "TARGET_REPLACE_TOKEN_3mN"
EDIT_NEW = "UPDATED_REPLACE_TOKEN_3mN"
EDIT2_OLD = "TARGET2_REPLACE_TOKEN_8vP"
EDIT2_NEW = "UPDATED2_REPLACE_TOKEN_8vP"
CONFIG_OLD = "CONFIG_ENTRY_TOKEN_k2M"
CONFIG_NEW = "UPDATED_CONFIG_ENTRY_TOKEN"

_BINARY_4K = (b"benchmark-bytes-" * 256)[:4096]
_BINARY_8K = (b"benchmark-bytes-" * 512)[:8192]



_FC_PARSER_PY = r'''from __future__ import annotations

import re
from typing import Any


# SEARCH_HIT_TOKEN_7qK: trace search marker alpha
PARSER_VERSION = "1.0.0"


def parse_config(raw: str) -> dict[str, Any]:
    """Parse a key=value config string."""
    result: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def parse_input(text: str) -> list[str]:
    """Tokenise free-form input."""
    return [t for t in re.split(r"\s+", text.strip()) if t]


# SEARCH_HIT_TOKEN_7qK: trace search marker beta
def validate_config(cfg: dict[str, Any]) -> bool:
    required = ["host", "port", "database"]
    return all(k in cfg for k in required)


def _normalize(value: str) -> str:
    return value.lower().strip()


def _expand_refs(text: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: m.group(1), text)


# TARGET_REPLACE_TOKEN_3mN
'''

_FC_CONFIG_PY = '''from __future__ import annotations

from dataclasses import dataclass


# SEARCH_HIT_TOKEN_7qK: config search marker
# CONFIG_ENTRY_TOKEN_k2M: default connection settings

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DB = "app_db"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30


@dataclass
class AppConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    database: str = DEFAULT_DB
    max_retries: int = MAX_RETRIES
    timeout: float = TIMEOUT_SECONDS

    def connection_string(self) -> str:
        return f"postgresql://{self.host}:{self.port}/{self.database}"
'''

_FC_ROUTES_PY = '''from __future__ import annotations

from typing import Any


# SEARCH_HIT_TOKEN_7qK: routes search marker alpha
ROUTE_VERSION = "1.0.0"


def get_user(user_id: str) -> dict[str, Any]:
    """Return user record."""
    return {"id": user_id, "status": "active"}


def list_users(page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
    """Return paginated user list."""
    return []


# SEARCH_HIT_TOKEN_7qK: routes search marker beta
def create_user(name: str, email: str) -> dict[str, Any]:
    return {"name": name, "email": email, "status": "pending"}


def delete_user(user_id: str) -> bool:
    return True


def _validate_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


# TARGET2_REPLACE_TOKEN_8vP
'''

_FC_TEST_PARSER = '''from __future__ import annotations

import pytest

from src.core.parser import parse_config, parse_input, validate_config


def test_parse_config_basic():
    raw = "host=localhost\nport=5432\ndatabase=app"
    result = parse_config(raw)
    assert result["host"] == "localhost"
    assert result["port"] == "5432"


def test_parse_input_tokens():
    assert parse_input("  hello world ") == ["hello", "world"]
    assert parse_input("") == []


def test_validate_config_ok():
    cfg = {"host": "localhost", "port": 5432, "database": "app"}
    assert validate_config(cfg) is True


def test_validate_config_missing():
    assert validate_config({}) is False
'''

_FC_CONFTEST = '''from __future__ import annotations

import pytest


@pytest.fixture
def sample_config():
    return {"host": "localhost", "port": 5432, "database": "test_db"}


@pytest.fixture
def raw_config_text():
    return "host=localhost\nport=5432\ndatabase=test_db"
'''

_FC_GUIDE_MD = '''# Developer Guide

This guide covers common development tasks.

## Setup

Install dependencies with `uv sync`.

## Configuration

Set environment variables or use a `.env` file.

## Testing

Run the test suite:

```bash
uv run pytest
```

## Code Style

Format and lint with ruff:

```bash
uv run ruff check .
```
'''

_FC_PYPROJECT_TOML = '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample-app"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.100", "psycopg[binary]>=3.1"]

[tool.ruff]
line-length = 100
'''

_FC_README_MD = '''# Sample App

A minimal web application backed by PostgreSQL.

## Installation

```bash
pip install -e .
```

## Usage

```python
from src.core.config import AppConfig
from src.core.parser import parse_config

cfg = AppConfig()
print(cfg.connection_string())
```

## Development

See [docs/guide.md](docs/guide.md) for the full developer guide.
'''

_FC_PKG_A_SUB_A1 = '''from __future__ import annotations

from typing import Any

# SEARCH_HIT_TOKEN_7qK: pkg_a.sub_a1 marker
COMPONENT = "pkg_a.sub_a1"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    """Initialize the sub_a1 component."""
    required = ["host", "port"]
    return all(k in config for k in required)


def process(data: list[Any]) -> list[Any]:
    """Process data items."""
    return [item for item in data if item is not None]


def shutdown() -> None:
    """Shutdown the component."""
    pass


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}


def _validate(item: Any) -> bool:
    return item is not None


# TARGET_REPLACE_TOKEN_3mN
'''

_FC_PKG_A_SUB_A2 = '''from __future__ import annotations

from typing import Any

COMPONENT = "pkg_a.sub_a2"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    return True


def process(data: list[Any]) -> list[Any]:
    return list(data)


def shutdown() -> None:
    pass


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}


def _validate(item: Any) -> bool:
    return True
'''

_FC_PKG_B_SUB_B1 = '''from __future__ import annotations

from typing import Any

# SEARCH_HIT_TOKEN_7qK: pkg_b.sub_b1 marker
COMPONENT = "pkg_b.sub_b1"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    required = ["endpoint", "timeout"]
    return all(k in config for k in required)


def connect(endpoint: str, timeout: int = 30) -> bool:
    return True


def disconnect() -> None:
    pass


def send(payload: dict[str, Any]) -> bool:
    return True


def receive() -> dict[str, Any]:
    return {}


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}
'''

_FC_PKG_B_SUB_B2 = '''from __future__ import annotations

from typing import Any

COMPONENT = "pkg_b.sub_b2"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    return True


def process(data: dict[str, Any]) -> dict[str, Any]:
    return data


def shutdown() -> None:
    pass


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}
'''

_FC_PKG_C_SUB_C1 = '''from __future__ import annotations

from typing import Any

COMPONENT = "pkg_c.sub_c1"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    return True


def transform(data: list[Any]) -> list[Any]:
    return data


def shutdown() -> None:
    pass


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}
'''

_FC_PKG_C_SUB_C2 = '''from __future__ import annotations

from typing import Any

# SEARCH_HIT_TOKEN_7qK: pkg_c.sub_c2 marker
COMPONENT = "pkg_c.sub_c2"
VERSION = "1.0.0"


def initialize(config: dict[str, Any]) -> bool:
    required = ["database", "schema"]
    return all(k in config for k in required)


def query(sql: str) -> list[dict[str, Any]]:
    return []


def execute(sql: str) -> int:
    return 0


def shutdown() -> None:
    pass


def get_status() -> dict[str, Any]:
    return {"component": COMPONENT, "version": VERSION, "status": "ok"}
'''

_FC_TEST_PKG_A = '''from __future__ import annotations

import pytest


def test_pkg_a_initialize():
    config = {"host": "localhost", "port": 5432}
    assert True


def test_pkg_a_process():
    data = [1, None, 2, None, 3]
    assert True


def test_pkg_a_status():
    assert True
'''

_FC_TEST_PKG_B = '''from __future__ import annotations

import pytest


def test_pkg_b_initialize():
    config = {"endpoint": "http://localhost", "timeout": 30}
    assert True


def test_pkg_b_connect():
    assert True


def test_pkg_b_status():
    assert True
'''

_FC_TEST_PKG_C = '''from __future__ import annotations

import pytest


def test_pkg_c_initialize():
    config = {"database": "mydb", "schema": "public"}
    assert True


def test_pkg_c_query():
    assert True


def test_pkg_c_status():
    assert True
'''

_FC_MAIN_PY = '''from __future__ import annotations

from typing import Any

# SEARCH_HIT_TOKEN_7qK: main module marker
MODULE = "main"
VERSION = "1.0.0"


def run(config: dict[str, Any]) -> int:
    """Main entry point."""
    if not config:
        return 1
    return 0


def load_config(path: str) -> dict[str, Any]:
    """Load configuration from file."""
    return {}


def validate(config: dict[str, Any]) -> bool:
    """Validate configuration."""
    return bool(config)


def shutdown() -> None:
    """Graceful shutdown."""
    pass


def _init() -> None:
    pass


# TARGET_REPLACE_TOKEN_3mN
'''

_FC_UTIL_PY = '''from __future__ import annotations

from typing import Any


def format_path(path: str) -> str:
    return path.strip("/")


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    result.update(override)
    return result


def chunked(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def flatten(nested: list[list]) -> list:
    return [item for sublist in nested for item in sublist]
'''

def _build_repo_like_small() -> list[tuple[str, str | bytes]]:
    return [
        ("src/core/parser.py", _FC_PARSER_PY),
        ("src/core/config.py", _FC_CONFIG_PY),
        ("src/api/routes.py", _FC_ROUTES_PY),
        ("tests/test_parser.py", _FC_TEST_PARSER),
        ("tests/conftest.py", _FC_CONFTEST),
        ("docs/guide.md", _FC_GUIDE_MD),
        ("pyproject.toml", _FC_PYPROJECT_TOML),
        ("README.md", _FC_README_MD),
    ]


def _build_repo_like_medium_deep() -> list[tuple[str, str | bytes]]:
    return [
        ("src/pkg_a/sub_a1/module.py", _FC_PKG_A_SUB_A1),
        ("src/pkg_a/sub_a2/module.py", _FC_PKG_A_SUB_A2),
        ("src/pkg_b/sub_b1/module.py", _FC_PKG_B_SUB_B1),
        ("src/pkg_b/sub_b2/module.py", _FC_PKG_B_SUB_B2),
        ("src/pkg_c/sub_c1/module.py", _FC_PKG_C_SUB_C1),
        ("src/pkg_c/sub_c2/module.py", _FC_PKG_C_SUB_C2),
        ("tests/pkg_a/test_module.py", _FC_TEST_PKG_A),
        ("tests/pkg_b/test_module.py", _FC_TEST_PKG_B),
        ("tests/pkg_c/test_module.py", _FC_TEST_PKG_C),
    ]


def _build_data_workspace() -> list[tuple[str, str | bytes]]:
    csv_rows = [
        f"{i + 1},item_{i:04d},{i * 10.5:.1f},{'status_A' if i % 5 == 0 else 'status_B'}"
        for i in range(50)
    ]
    csv_content = "\n".join(["id,name,value,status"] + csv_rows) + "\n"

    log_01_lines = []
    for i in range(60):
        if i in {10, 20, 30, 40, 50}:
            log_01_lines.append(f"2024-01-01 12:00:00 ERROR: SEARCH_HIT_TOKEN_7qK id={i:04d}")
        else:
            log_01_lines.append(f"2024-01-01 12:00:00 INFO: Processing record id={i:04d} status=ok")
    log_01 = "\n".join(log_01_lines) + "\n"

    log_02_lines = []
    for i in range(60):
        if i in {10, 20, 30, 40, 50}:
            log_02_lines.append(f"2024-02-01 12:00:00 ERROR: SEARCH_HIT_TOKEN_7qK id={i:04d}")
        else:
            log_02_lines.append(f"2024-02-01 12:00:00 INFO: Processing record id={i:04d} status=ok")
    log_02 = "\n".join(log_02_lines) + "\n"

    summary_01 = (
        "{\n"
        '  "period": "2024-01",\n'
        '  "total_records": 50,\n'
        '  "status_A_count": 10,\n'
        '  "status_B_count": 40,\n'
        '  "total_value": 13125.0,\n'
        '  "mean_value": 262.5,\n'
        '  "min_value": 0.0,\n'
        '  "max_value": 517.5,\n'
        '  "generated_at": "2024-02-01T00:00:00Z"\n'
        "}\n"
    )
    summary_02 = (
        "{\n"
        '  "period": "2024-02",\n'
        '  "total_records": 50,\n'
        '  "status_A_count": 10,\n'
        '  "status_B_count": 40,\n'
        '  "total_value": 13125.0,\n'
        '  "mean_value": 262.5,\n'
        '  "min_value": 0.0,\n'
        '  "max_value": 517.5,\n'
        '  "generated_at": "2024-03-01T00:00:00Z"\n'
        "}\n"
    )

    return [
        ("data/raw/records_2024_01.csv", csv_content),
        ("data/raw/records_2024_02.csv", csv_content),
        ("data/processed/summary_2024_01.json", summary_01),
        ("data/processed/summary_2024_02.json", summary_02),
        ("logs/app_2024_01.log", log_01),
        ("logs/app_2024_02.log", log_02),
    ]


def _build_wide_flat_tree() -> list[tuple[str, str | bytes]]:
    notes = [
        (
            f"notes/note_{i:04d}.txt",
            f"note content: SEARCH_HIT_TOKEN_7qK index={i:04d}\n"
            if 40 <= i <= 49
            else f"note content: normal text index={i:04d}\n",
        )
        for i in range(75)
    ]
    index_txt = (
        "Note Archive Index\n"
        "==================\n"
        "Total notes: 75\n"
        "Indexed: 2024-01-01\n"
    )
    return notes + [("notes/index.txt", index_txt)]



def _build_binary_artifact_mix() -> list[tuple[str, str | bytes]]:
    return [
        ("src/main.py", _FC_MAIN_PY),
        ("src/util.py", _FC_UTIL_PY),
        ("blobs/blob_000.bin", _BINARY_4K),
        ("blobs/blob_001.bin", _BINARY_4K),
        ("blobs/blob_002.bin", _BINARY_8K),
        ("blobs/blob_003.bin", _BINARY_4K),
    ]


FIXTURE_CONTENT: dict[str, list[tuple[str, str | bytes]]] = {
    "repo_like_small": _build_repo_like_small(),
    "repo_like_medium_deep": _build_repo_like_medium_deep(),
    "data_workspace": _build_data_workspace(),
    "wide_flat_tree": _build_wide_flat_tree(),
    "binary_artifact_mix": _build_binary_artifact_mix(),
}


@dataclass
class TraceStep:
    step: int
    op: str
    args: dict[str, Any]
    expected: str = "ok"


@dataclass
class Trace:
    id: str
    fixture_id: str
    steps: list[TraceStep]
    tags: dict[str, str]
    suite: str = "realistic"


TRACES: list[Trace] = [
    Trace(
        "T01_short_ls_read",
        "repo_like_small",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "aread", {"path": "src/core/parser.py"}),
        ],
        tags={"shape": "short·linear"},
    ),
    Trace(
        "T02_short_glob_read",
        "repo_like_small",
        steps=[
            TraceStep(1, "aglob_info", {"pattern": "**/*.py", "path": "src"}),
            TraceStep(2, "aread", {"path": "src/core/parser.py"}),
            TraceStep(3, "aread", {"path": "src/api/routes.py"}),
        ],
        tags={"shape": "short·discovery-heavy"},
    ),
    Trace(
        "T03_short_upload_download",
        "binary_artifact_mix",
        steps=[
            TraceStep(1, "aupload_files", {"files": [("blobs/new_artifact.bin", _BINARY_4K)]}),
            TraceStep(2, "adownload_files", {"paths": ["blobs/new_artifact.bin"]}),
        ],
        tags={"shape": "short·linear"},
    ),
    Trace(
        "T04_short_miss_recover",
        "repo_like_small",
        steps=[
            TraceStep(1, "aread", {"path": "src/core/missing.py"}, expected="not_found"),
            TraceStep(2, "als_info", {"path": "src/core"}),
            TraceStep(3, "aread", {"path": "src/core/config.py"}),
        ],
        tags={"shape": "short·retry-error"},
    ),
    Trace(
        "T05_medium_discover_edit",
        "repo_like_small",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "aglob_info", {"pattern": "**/*.py", "path": "src"}),
            TraceStep(3, "aread", {"path": "src/core/parser.py"}),
            TraceStep(4, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(
                5, "aedit",
                {"path": "src/core/parser.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(6, "aread", {"path": "src/core/parser.py"}),
        ],
        tags={"shape": "medium·discovery-heavy"},
    ),
    Trace(
        "T06_medium_paginated_read_write",
        "data_workspace",
        steps=[
            TraceStep(1, "als_info", {"path": "data/raw"}),
            TraceStep(2, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "logs"}),
            TraceStep(3, "aread", {"path": "logs/app_2024_01.log", "offset": 0, "limit": 30}),
            TraceStep(4, "aread", {"path": "logs/app_2024_01.log", "offset": 30, "limit": 30}),
            TraceStep(
                5, "awrite",
                    {
                        "path": "reports/incident_report.md",
                        "content": "# Incident Report\n\nLog analysis complete.\n",
                    }
            ),
            TraceStep(6, "aread", {"path": "reports/incident_report.md"}),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T07_medium_multi_file_inspect",
        "data_workspace",
        steps=[
            TraceStep(1, "aglob_info", {"pattern": "**/*.json", "path": "data"}),
            TraceStep(2, "aread", {"path": "data/processed/summary_2024_01.json"}),
            TraceStep(3, "aread", {"path": "data/processed/summary_2024_02.json"}),
            TraceStep(
                4, "awrite",
                    {
                        "path": "reports/combined_summary.md",
                        "content": "# Combined Summary\n\nAggregated data.\n",
                    }
            ),
            TraceStep(5, "als_info", {"path": "reports"}),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T08_medium_import_validate",
        "binary_artifact_mix",
        steps=[
            TraceStep(
                1, "aupload_files",
                {"files": [("blobs/upload_a.bin", _BINARY_4K), ("blobs/upload_b.bin", _BINARY_4K)]}
            ),
            TraceStep(2, "als_info", {"path": "blobs"}),
            TraceStep(3, "aread", {"path": "src/main.py"}),
            TraceStep(4, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(
                5, "awrite",
                {"path": "src/report.txt", "content": "Import validation complete.\n"}
            ),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T09_medium_verify_heavy",
        "repo_like_small",
        steps=[
            TraceStep(1, "aread", {"path": "src/core/parser.py"}),
            TraceStep(
                2, "aedit",
                {"path": "src/core/parser.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(3, "aread", {"path": "src/core/parser.py"}),
            TraceStep(4, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(5, "aread", {"path": "src/api/routes.py"}),
            TraceStep(6, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src/api"}),
        ],
        tags={"shape": "medium·verification-heavy"},
    ),
    Trace(
        "T10_medium_deep_discover",
        "repo_like_medium_deep",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "als_info", {"path": "src/pkg_a"}),
            TraceStep(3, "aglob_info", {"pattern": "**/*.py", "path": "src/pkg_a"}),
            TraceStep(4, "aread", {"path": "src/pkg_a/sub_a1/module.py"}),
            TraceStep(5, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src/pkg_a"}),
            TraceStep(
                6, "awrite",
                {"path": "src/pkg_a/sub_a1/output.py", "content": "# generated output\n"}
            ),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T11_medium_wide_grep",
        "wide_flat_tree",
        steps=[
            TraceStep(1, "als_info", {"path": "notes"}),
            TraceStep(2, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "notes"}),
            TraceStep(3, "aread", {"path": "notes/note_0040.txt"}),
            TraceStep(4, "aread", {"path": "notes/note_0041.txt"}),
            TraceStep(
                5, "awrite",
                    {
                        "path": "notes/grep_summary.txt",
                        "content": "# Grep Summary\n\nFound 10 matching notes.\n",
                    }
            ),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T12_medium_data_aggregate",
        "data_workspace",
        steps=[
            TraceStep(1, "aglob_info", {"pattern": "**/*.csv", "path": "data"}),
            TraceStep(2, "aread", {"path": "data/raw/records_2024_01.csv"}),
            TraceStep(3, "aread", {"path": "data/raw/records_2024_02.csv"}),
            TraceStep(
                4, "awrite",
                {"path": "reports/merged_records.csv", "content": "id,name,value,status\n"}
            ),
            TraceStep(5, "als_info", {"path": "reports"}),
        ],
        tags={"shape": "medium·linear"},
    ),
    Trace(
        "T13_medium_edit_verify",
        "repo_like_small",
        steps=[
            TraceStep(1, "aread", {"path": "src/core/config.py"}),
            TraceStep(2, "agrep_raw", {"pattern": CONFIG_OLD, "path": "src/core"}),
            TraceStep(
                3, "aedit",
                {"path": "src/core/config.py", "old_string": CONFIG_OLD, "new_string": CONFIG_NEW}
            ),
            TraceStep(4, "aread", {"path": "src/core/config.py"}),
            TraceStep(5, "agrep_raw", {"pattern": CONFIG_OLD, "path": "src/core"}, expected="no_match"),
        ],
        tags={"shape": "medium·verification-heavy"},
    ),
    Trace(
        "T14_medium_miss_then_edit",
        "repo_like_small",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "aread", {"path": "src/core/missing.py"}, expected="not_found"),
            TraceStep(3, "aglob_info", {"pattern": "**/*.py", "path": "src/core"}),
            TraceStep(4, "aread", {"path": "src/core/parser.py"}),
            TraceStep(
                5, "aedit",
                {"path": "src/core/parser.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(
                6, "awrite",
                {"path": "docs/findings.md", "content": "# Findings\n\nRecovered from missing file.\n"}
            ),
        ],
        tags={"shape": "medium·retry-error"},
    ),
    Trace(
        "T15_long_multi_touch",
        "repo_like_small",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "aglob_info", {"pattern": "**/*.py", "path": "src"}),
            TraceStep(3, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(4, "aread", {"path": "src/core/parser.py"}),
            TraceStep(5, "aread", {"path": "src/api/routes.py"}),
            TraceStep(
                6, "aedit",
                {"path": "src/core/parser.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(
                7, "aedit",
                {"path": "src/api/routes.py", "old_string": EDIT2_OLD, "new_string": EDIT2_NEW}
            ),
            TraceStep(
                8, "awrite",
                    {
                        "path": "docs/changelog.md",
                        "content": "# Changelog\n\n## v1.1.0\n- Updated parser\n- Updated routes\n",
                    }
            ),
            TraceStep(9, "aread", {"path": "docs/changelog.md"}),
            TraceStep(10, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(11, "als_info", {"path": "docs"}),
        ],
        tags={"shape": "long·linear"},
    ),
    Trace(
        "T16_long_paginated_scan",
        "data_workspace",
        steps=[
            TraceStep(1, "als_info", {"path": "data/raw"}),
            TraceStep(2, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "logs"}),
            TraceStep(3, "aread", {"path": "logs/app_2024_01.log", "offset": 0, "limit": 30}),
            TraceStep(4, "aread", {"path": "logs/app_2024_01.log", "offset": 30, "limit": 30}),
            TraceStep(5, "aread", {"path": "logs/app_2024_01.log", "offset": 60, "limit": 30}),
            TraceStep(6, "aglob_info", {"pattern": "**/*.csv", "path": "data"}),
            TraceStep(7, "aread", {"path": "data/raw/records_2024_01.csv"}),
            TraceStep(8, "aread", {"path": "data/raw/records_2024_02.csv"}),
            TraceStep(
                9, "aedit",
                    {
                        "path": "data/raw/records_2024_01.csv",
                        "old_string": "status_A",
                        "new_string": "status_PROCESSED",
                    }
            ),
            TraceStep(
                10, "awrite",
                {"path": "reports/analysis_report.md", "content": "# Analysis\n\nData processed.\n"}
            ),
            TraceStep(11, "aread", {"path": "reports/analysis_report.md"}),
            TraceStep(12, "als_info", {"path": "reports"}),
        ],
        tags={"shape": "long·linear"},
    ),
    Trace(
        "T17_long_import_export",
        "binary_artifact_mix",
        steps=[
            TraceStep(
                1, "aupload_files",
                {"files": [("blobs/blob_100.bin", _BINARY_4K), ("blobs/blob_101.bin", _BINARY_4K)]}
            ),
            TraceStep(2, "als_info", {"path": "blobs"}),
            TraceStep(3, "aglob_info", {"pattern": "**/*.bin", "path": "blobs"}),
            TraceStep(4, "aread", {"path": "src/main.py"}),
            TraceStep(5, "aread", {"path": "src/util.py"}),
            TraceStep(6, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(
                7, "aedit",
                {"path": "src/main.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(
                8, "awrite",
                    {
                        "path": "src/manifest.txt",
                        "content": "blob_000.bin\nblob_001.bin\nblob_100.bin\nblob_101.bin\n",
                    }
            ),
            TraceStep(9, "adownload_files", {"paths": ["blobs/blob_000.bin", "blobs/blob_001.bin"]}),
        ],
        tags={"shape": "long·linear"},
    ),
    Trace(
        "T18_long_deep_discover",
        "repo_like_medium_deep",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "als_info", {"path": "src/pkg_a"}),
            TraceStep(3, "als_info", {"path": "src/pkg_b"}),
            TraceStep(4, "aglob_info", {"pattern": "**/*.py", "path": "src/pkg_a"}),
            TraceStep(5, "aglob_info", {"pattern": "**/*.py", "path": "src/pkg_b"}),
            TraceStep(6, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src/pkg_a"}),
            TraceStep(7, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src/pkg_b"}),
            TraceStep(8, "aread", {"path": "src/pkg_a/sub_a1/module.py"}),
            TraceStep(9, "aread", {"path": "src/pkg_b/sub_b1/module.py"}),
            TraceStep(
                10, "aedit",
                {"path": "src/pkg_a/sub_a1/module.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(
                11, "awrite",
                {"path": "tests/pkg_a/test_output.py", "content": "# test output\n"}
            ),
        ],
        tags={"shape": "long·discovery-heavy"},
    ),
    Trace(
        "T19_long_wide_aggregate",
        "wide_flat_tree",
        steps=[
            TraceStep(1, "als_info", {"path": "notes"}),
            TraceStep(2, "aglob_info", {"pattern": "**/*.txt", "path": "notes"}),
            TraceStep(3, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "notes"}),
            TraceStep(4, "aread", {"path": "notes/note_0040.txt"}),
            TraceStep(5, "aread", {"path": "notes/note_0041.txt"}),
            TraceStep(6, "aread", {"path": "notes/note_0042.txt"}),
            TraceStep(
                7, "awrite",
                {"path": "notes/digest.txt", "content": "# Digest\n\nProcessed 10 matching notes.\n"}
            ),
            TraceStep(8, "adownload_files", {"paths": ["notes/note_0040.txt", "notes/note_0041.txt"]}),
        ],
        tags={"shape": "long·linear"},
    ),
    Trace(
        "T20_vlong_full_workflow",
        "repo_like_small",
        steps=[
            TraceStep(1, "als_info", {"path": "src"}),
            TraceStep(2, "aglob_info", {"pattern": "**/*.py", "path": "src"}),
            TraceStep(3, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(4, "aread", {"path": "src/core/parser.py", "offset": 0, "limit": 20}),
            TraceStep(5, "aread", {"path": "src/core/parser.py", "offset": 20, "limit": 20}),
            TraceStep(6, "aread", {"path": "src/api/routes.py"}),
            TraceStep(
                7, "aedit",
                {"path": "src/core/parser.py", "old_string": EDIT_OLD, "new_string": EDIT_NEW}
            ),
            TraceStep(
                8, "aedit",
                {"path": "src/api/routes.py", "old_string": EDIT2_OLD, "new_string": EDIT2_NEW}
            ),
            TraceStep(
                9, "awrite",
                {"path": "src/core/result.py", "content": "# result module\nRESULT = 'ok'\n"}
            ),
            TraceStep(
                10, "awrite",
                {"path": "docs/report.md", "content": "# Report\n\nFull workflow complete.\n"}
            ),
            TraceStep(11, "aread", {"path": "src/core/result.py"}),
            TraceStep(12, "agrep_raw", {"pattern": SEARCH_NEEDLE, "path": "src"}),
            TraceStep(13, "als_info", {"path": "src/core"}),
            TraceStep(14, "aread", {"path": "src/core/config.py"}),
            TraceStep(15, "agrep_raw", {"pattern": CONFIG_OLD, "path": "src/core"}),
            TraceStep(
                16, "aedit",
                {"path": "src/core/config.py", "old_string": CONFIG_OLD, "new_string": CONFIG_NEW}
            ),
            TraceStep(17, "aupload_files", {"files": [("artifacts/artifact.bin", _BINARY_4K)]}),
            TraceStep(18, "als_info", {"path": "docs"}),
            TraceStep(19, "adownload_files", {"paths": ["docs/report.md"]}),
            TraceStep(20, "aread", {"path": "docs/report.md"}),
        ],
        tags={"shape": "vlong·verification-heavy"},
    ),
]


def _normalize_fs_read(result: Any) -> str:
    if result.error:
        msg = result.error.lower()
        return "not_found" if "not found" in msg else "invalid_request"
    return "ok"


def _normalize_str_result(result: str) -> str:
    if result.startswith("Error:"):
        msg = result.lower()
        if "not found" in msg:
            return "not_found"
        if "already exists" in msg:
            return "already_exists"
        return "invalid_request"
    return "ok"


def _normalize_write_result(result: Any) -> str:
    if result.error:
        msg = result.error.lower()
        if "already exists" in msg:
            return "already_exists"
        return "invalid_request"
    return "ok"


def _normalize_edit_result(result: Any) -> str:
    if result.error:
        msg = result.error.lower()
        if "string not found" in msg:
            return "no_match"
        if "not found" in msg:
            return "not_found"
        return "invalid_request"
    if result.occurrences == 0:
        return "no_match"
    return "ok"


def _normalize_list_result(result: list | str) -> str:
    if isinstance(result, str):
        return "invalid_request"
    if not result:
        return "empty_result"
    return "ok"


def _normalize_grep_result(result: list | str) -> str:
    if isinstance(result, str):
        return "invalid_request"
    if not result:
        return "no_match"
    return "ok"


def _normalize_upload_result(result: list | str) -> str:
    if isinstance(result, str):
        return "invalid_request"
    errors = [r for r in result if r.error]
    if errors:
        msg = errors[0].error.lower()
        if "not found" in msg:
            return "not_found"
        return "invalid_request"
    return "ok"


def _normalize_download_result(result: list | str) -> str:
    if isinstance(result, str):
        return "invalid_request"
    errors = [r for r in result if r.error]
    if errors:
        msg = errors[0].error.lower()
        if "not found" in msg:
            return "not_found"
        return "invalid_request"
    return "ok"


@dataclass
class StepResult:
    step: int
    op: str
    elapsed_ms: float
    expected: str
    actual: str
    correct: bool


@dataclass
class TraceRunResult:
    trace_id: str
    iteration: int
    total_ms: float
    steps: list[StepResult]
    correct: bool


@dataclass
class TraceAggResult:
    trace_id: str
    fixture_id: str
    tags: dict[str, str]
    backend: str
    suite: str
    runs: list[TraceRunResult]
    median_total_ms: float
    mean_total_ms: float
    min_total_ms: float
    max_total_ms: float
    samples_total_ms: list[float]
    correctness_rate: float
    per_op_stats: dict[str, dict[str, float]]


def _resolve_args(args: dict[str, Any], root: str) -> dict[str, Any]:
    resolved = {}
    for k, v in args.items():
        if k == "path" and isinstance(v, str):
            resolved[k] = f"{root}/{v}" if v else root
        elif k == "paths" and isinstance(v, list):
            resolved[k] = [f"{root}/{p}" for p in v]
        elif k == "files" and isinstance(v, list):
            resolved[k] = [(f"{root}/{p}", b) for p, b in v]
        else:
            resolved[k] = v
    return resolved


class FilesystemAsyncAdapter:
    name = "filesystem"

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self._backend: FilesystemBackend | None = None

    def infra_setup(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._backend = FilesystemBackend(root_dir=self.runtime_dir, virtual_mode=True)

    async def async_setup(self) -> None:
        pass

    async def async_teardown(self) -> None:
        pass

    def infra_teardown(self) -> None:
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_fs_read(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class S3AsyncAdapter:
    name = "minio_s3"

    def __init__(self, prefix: str) -> None:
        self._backend = S3Backend(
            S3Config(
                bucket=MINIO_BUCKET,
                prefix=prefix,
                endpoint_url=MINIO_ENDPOINT,
                access_key_id="minioadmin",
                secret_access_key="minioadmin",
                use_ssl=False,
                region="us-east-1",
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        await ensure_minio_bucket()

    async def async_teardown(self) -> None:
        pass

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class PostgresAsyncAdapter:
    name = "postgres"

    def __init__(self, table: str) -> None:
        self._backend = PostgresBackend(
            PostgresConfig(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                database=POSTGRES_DATABASE,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                table=table,
                min_pool_size=2,
                max_pool_size=10,
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        await self._backend.initialize()

    async def async_teardown(self) -> None:
        await self._backend.close()

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class AzureBlobAsyncAdapter:
    name = "azure_blob"

    def __init__(self, prefix: str) -> None:
        self._backend = AzureBlobBackend(
            AzureBlobConfig(
                container=AZURE_CONTAINER,
                prefix=prefix,
                connection_string=AZURE_BLOB_CONNECTION_STRING,
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        await self._backend.ensure_container()

    async def async_teardown(self) -> None:
        await self._backend.close()

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class GCSAsyncAdapter:
    name = "gcs"

    def __init__(self, prefix: str) -> None:
        self._backend = GCSBackend(
            GCSConfig(
                bucket=GCS_BUCKET,
                prefix=prefix,
                api_root=GCS_API_ROOT,
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        await asyncio.to_thread(ensure_fake_gcs_bucket)

    async def async_teardown(self) -> None:
        await self._backend.close()

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class MongoDBAsyncAdapter:
    name = "mongodb"

    def __init__(self, collection: str) -> None:
        self._collection_name = collection
        self._backend = MongoDBBackend(
            MongoDBConfig(
                connection_uri=MONGODB_URI,
                database=MONGODB_DATABASE,
                collection=collection,
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        await self._backend.initialize()

    async def async_teardown(self) -> None:
        collection = await self._backend._ensure_collection()
        await collection.drop()
        await self._backend.close()

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


class RedisAsyncAdapter:
    name = "redis"

    def __init__(self, namespace: str, prefix: str) -> None:
        self._backend = RedisBackend(
            RedisConfig(
                url=REDIS_URL,
                namespace=namespace,
                prefix=prefix,
            )
        )

    def infra_setup(self) -> None:
        pass

    async def async_setup(self) -> None:
        pass

    async def async_teardown(self) -> None:
        client = await self._backend._ensure_client()
        members = await client.smembers(self._backend._index_key)
        data_keys = []
        for member in members:
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            data_keys.append(f"{self._backend._namespace}:file:{member}")
        if data_keys:
            await client.delete(*data_keys)
        await client.delete(self._backend._index_key)
        await self._backend.close()

    def infra_teardown(self) -> None:
        pass

    async def write_fixture_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            await self._backend.aupload_files([(path, content)])
        else:
            await self._backend.awrite(path, content)

    async def run_step(self, op: str, args: dict) -> tuple[float, str]:
        start = time.perf_counter_ns()
        outcome = await self._dispatch(op, args)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms, outcome

    async def _dispatch(self, op: str, args: dict) -> str:
        if op == "aread":
            result = await self._backend.aread(
                args["path"], args.get("offset", 0), args.get("limit", 2000)
            )
            return _normalize_str_result(result)
        elif op == "awrite":
            result = await self._backend.awrite(args["path"], args["content"])
            return _normalize_write_result(result)
        elif op == "aedit":
            result = await self._backend.aedit(args["path"], args["old_string"], args["new_string"])
            return _normalize_edit_result(result)
        elif op == "als_info":
            result = await self._backend.als_info(args["path"])
            return _normalize_list_result(result)
        elif op == "aglob_info":
            result = await self._backend.aglob_info(args["pattern"], args.get("path", "/"))
            return _normalize_grep_result(result)
        elif op == "agrep_raw":
            result = await self._backend.agrep_raw(args["pattern"], args.get("path"), args.get("glob"))
            return _normalize_grep_result(result)
        elif op == "aupload_files":
            result = await self._backend.aupload_files(args["files"])
            return _normalize_upload_result(result)
        elif op == "adownload_files":
            result = await self._backend.adownload_files(args["paths"])
            return _normalize_download_result(result)
        return "invalid_request"


async def ensure_minio_bucket() -> None:
    session = aioboto3.Session(
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
    )
    async with session.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        region_name="us-east-1",
        use_ssl=False,
    ) as s3:
        try:
            await s3.create_bucket(Bucket=MINIO_BUCKET)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            return
        except s3.exceptions.BucketAlreadyExists:
            return


def ensure_fake_gcs_bucket() -> None:
    request = urllib.request.Request(
        f"{GCS_API_ROOT}/storage/v1/b?project=benchmark-project",
        data=json.dumps({"name": GCS_BUCKET}).encode("utf-8"),
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


def run_compose(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        check=True,
    )


async def replay_trace(
    adapter: Any,
    trace: Trace,
    run_id: str,
    iteration: int,
    warmup: bool = False,
) -> TraceRunResult | None:
    root = f"/{run_id}/{trace.id}/it{iteration:02d}"

    for rel_path, content in FIXTURE_CONTENT[trace.fixture_id]:
        full_path = f"{root}/{rel_path}"
        await adapter.write_fixture_file(full_path, content)

    if warmup:
        for step in trace.steps:
            resolved = _resolve_args(step.args, root)
            await adapter.run_step(step.op, resolved)
        return None

    step_results = []
    for step in trace.steps:
        resolved = _resolve_args(step.args, root)
        elapsed_ms, actual = await adapter.run_step(step.op, resolved)
        step_results.append(
            StepResult(
                step=step.step,
                op=step.op,
                elapsed_ms=elapsed_ms,
                expected=step.expected,
                actual=actual,
                correct=(actual == step.expected),
            )
        )

    total_ms = sum(s.elapsed_ms for s in step_results)
    all_correct = all(s.correct for s in step_results)
    return TraceRunResult(trace.id, iteration, total_ms, step_results, all_correct)


async def benchmark_backend_async(
    adapter: Any,
    traces: list[Trace],
    *,
    run_id: str,
    warmup_runs: int,
    measured_runs: int,
) -> list[TraceAggResult]:
    results = []
    for trace in traces:
        run_results = []
        total_iters = warmup_runs + measured_runs
        for iteration in range(total_iters):
            is_warmup = iteration < warmup_runs
            run_result = await replay_trace(adapter, trace, run_id, iteration, warmup=is_warmup)
            if run_result is not None:
                run_results.append(run_result)

        totals = [r.total_ms for r in run_results]
        per_op: dict[str, list[float]] = {}
        for run in run_results:
            for step in run.steps:
                per_op.setdefault(step.op, []).append(step.elapsed_ms)
        per_op_stats = {
            op: {
                "p50": statistics.median(times),
                "mean": statistics.fmean(times),
                "count": float(len(times)),
            }
            for op, times in per_op.items()
        }

        results.append(
            TraceAggResult(
                trace_id=trace.id,
                fixture_id=trace.fixture_id,
                tags=trace.tags,
                backend=adapter.name,
                suite=trace.suite,
                runs=run_results,
                median_total_ms=statistics.median(totals),
                mean_total_ms=statistics.fmean(totals),
                min_total_ms=min(totals),
                max_total_ms=max(totals),
                samples_total_ms=totals,
                correctness_rate=sum(r.correct for r in run_results) / len(run_results),
                per_op_stats=per_op_stats,
            )
        )
    return results


async def run_all_async(
    adapters: list[Any],
    traces: list[Trace],
    *,
    run_id: str,
    warmup_runs: int,
    measured_runs: int,
) -> list[TraceAggResult]:
    all_results = []
    for adapter in adapters:
        adapter.infra_setup()
        await adapter.async_setup()
        try:
            results = await benchmark_backend_async(
                adapter,
                traces,
                run_id=run_id,
                warmup_runs=warmup_runs,
                measured_runs=measured_runs,
            )
            all_results.extend(results)
        finally:
            await adapter.async_teardown()
            adapter.infra_teardown()
    return all_results


def build_async_adapters(run_id: str) -> list[Any]:
    table_suffix = hashlib.sha1(run_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    fs_dir = Path.home() / ".cache" / "deepagents-backends-bm" / run_id / "filesystem"
    return [
        FilesystemAsyncAdapter(fs_dir),
        PostgresAsyncAdapter(f"bm_{table_suffix}"),
        S3AsyncAdapter(f"bm/{run_id}/minio"),
        AzureBlobAsyncAdapter(f"bm/{run_id}/azure"),
        GCSAsyncAdapter(f"bm/{run_id}/gcs"),
        MongoDBAsyncAdapter(f"bm_{table_suffix[:12]}_mongo"),
        RedisAsyncAdapter(f"bm-{run_id[:8]}-redis", f"bm/{run_id}/redis"),
    ]


def build_payload(
    *,
    run_id: str,
    results: list[TraceAggResult],
    measured_runs: int,
    warmup_runs: int,
    managed_services: bool,
    results_path: Path,
) -> dict[str, Any]:
    by_trace: dict[str, list[TraceAggResult]] = {}
    for r in results:
        by_trace.setdefault(r.trace_id, []).append(r)

    backend_order = ["filesystem", "postgres", "minio_s3", "azure_blob", "gcs", "mongodb", "redis"]

    try:
        results_path_display = str(results_path.relative_to(REPO_ROOT))
    except ValueError:
        results_path_display = str(results_path)

    trace_payloads = []
    for trace in TRACES:
        if trace.suite != "realistic":
            continue
        trace_results = by_trace.get(trace.id, [])
        by_backend = {r.backend: r for r in trace_results}
        trace_payloads.append(
            {
                "trace_id": trace.id,
                "fixture_id": trace.fixture_id,
                "tags": trace.tags,
                "suite": trace.suite,
                "step_count": len(trace.steps),
                "backends": {
                    backend: {
                        "median_total_ms": by_backend[backend].median_total_ms,
                        "mean_total_ms": by_backend[backend].mean_total_ms,
                        "min_total_ms": by_backend[backend].min_total_ms,
                        "max_total_ms": by_backend[backend].max_total_ms,
                        "samples_total_ms": by_backend[backend].samples_total_ms,
                        "correctness_rate": by_backend[backend].correctness_rate,
                        "per_op_stats": by_backend[backend].per_op_stats,
                        "run_details": [
                            {
                                "iteration": run.iteration,
                                "total_ms": run.total_ms,
                                "correct": run.correct,
                                "steps": [
                                    {
                                        "step": s.step,
                                        "op": s.op,
                                        "elapsed_ms": s.elapsed_ms,
                                        "expected": s.expected,
                                        "actual": s.actual,
                                        "correct": s.correct,
                                    }
                                    for s in run.steps
                                ],
                            }
                            for run in by_backend[backend].runs
                        ],
                    }
                    for backend in backend_order
                    if backend in by_backend
                },
            }
        )

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id,
        "warmup_runs": warmup_runs,
        "measured_runs": measured_runs,
        "managed_services": managed_services,
        "results_path": results_path_display,
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "suite": "realistic",
        "traces": trace_payloads,
    }


def build_markdown_report(payload: dict[str, Any]) -> str:
    backend_order = ["filesystem", "postgres", "minio_s3", "azure_blob", "gcs", "mongodb", "redis"]
    backend_labels = {
        "filesystem": "Filesystem",
        "postgres": "PostgreSQL",
        "minio_s3": "MinIO S3",
        "azure_blob": "Azure Blob",
        "gcs": "GCS",
        "mongodb": "MongoDB",
        "redis": "Redis/Valkey",
    }
    env = payload["environment"]
    lines = [
        "# Benchmark Results",
        "",
        "This folder contains a reproducible **realistic trace-based benchmark** for seven "
        "file-oriented backends:",
        "",
        "- `FilesystemBackend` from `deepagents`, scoped to a dedicated root directory with
        `virtual_mode=True`.",
        "- `PostgresBackend` from this repository, backed by Dockerized PostgreSQL.",
        "- `S3Backend` from this repository, backed by Dockerized MinIO.",
        "- `AzureBlobBackend` from this repository, backed by Dockerized Azurite.",
        "- `GCSBackend` from this repository, backed by Dockerized fake-gcs-server.",
        "- `MongoDBBackend` from this repository, backed by Dockerized MongoDB.",
        "- `RedisBackend` from this repository, backed by Dockerized Valkey.",
        "",
        "## How to run",
        "",
        "```bash",
        "cd /home/runner/work/deepagents-backends/deepagents-backends",
        "uv run python benchmark/run.py --manage-services --write-readme",
        "```",
        "",
        "## Methodology",
        "",
        "Each benchmark run replays a **filesystem trace**: a fixed sequence of async backend "
        "operations (`aread`, `awrite`, `aedit`, `als_info`, `aglob_info`, `agrep_raw`, "
        "`aupload_files`, `adownload_files`) on a pre-populated fixture set.",
        "",
        f"- Warmup runs per trace: `{payload['warmup_runs']}`",
        f"- Measured runs per trace: `{payload['measured_runs']}`",
        "- Fixture setup is excluded from timing; only the trace steps are measured.",
        "- Each run uses a unique path prefix so iterations are fully isolated.",
        "- Outcome correctness is checked per step (expected vs. actual normalized outcome).",
        "",
        "## Environment",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Python: `{env['python_version']}`",
        f"- Platform: `{env['platform']}`",
        f"- Machine: `{env['machine']}`",
        f"- Docker managed by script: `{payload['managed_services']}`",
        "",
        "## Realistic replay suite",
        "",
        "### Median total trace latency (ms)",
        "",
    ]

    header_cols = (
        ["Trace", "Shape", "Fixture"]
        + [backend_labels[b] for b in backend_order]
        + ["Fastest"]
    )
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|" + "|".join(["---"] * 3 + ["---:"] * len(backend_order) + ["---"]) + "|")

    for trace_data in payload["traces"]:
        trace_id = trace_data["trace_id"]
        shape = trace_data["tags"].get("shape", "")
        fixture = trace_data["fixture_id"]
        backends_data = trace_data["backends"]
        medians = {b: backends_data[b]["median_total_ms"] for b in backend_order if b in backends_data}
        if medians:
            fastest = min(medians, key=medians.get)
            fastest_label = backend_labels.get(fastest, fastest)
        else:
            fastest_label = "-"

        row = [f"`{trace_id}`", shape, fixture]
        for b in backend_order:
            row.append(f"{medians[b]:.1f}" if b in medians else "-")
        row.append(fastest_label)
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "### Per-op latency summary (p50 across all traces, ms)",
            "",
        ]
    )

    all_ops: set[str] = set()
    for trace_data in payload["traces"]:
        for b_data in trace_data["backends"].values():
            all_ops.update(b_data["per_op_stats"].keys())
    op_order = sorted(all_ops)

    op_header = ["Op"] + [backend_labels[b] for b in backend_order]
    lines.append("| " + " | ".join(op_header) + " |")
    lines.append("|" + "|".join(["---"] + ["---:"] * len(backend_order)) + "|")

    for op in op_order:
        row = [f"`{op}`"]
        for b in backend_order:
            p50s = []
            for trace_data in payload["traces"]:
                bdata = trace_data["backends"].get(b, {})
                op_stats = bdata.get("per_op_stats", {}).get(op)
                if op_stats:
                    p50s.append(op_stats["p50"])
            row.append(f"{statistics.fmean(p50s):.1f}" if p50s else "-")
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "### Correctness pass rate",
            "",
            "| Backend | Rate |",
            "|---|---:|",
        ]
    )

    for b in backend_order:
        rates = []
        for trace_data in payload["traces"]:
            bdata = trace_data["backends"].get(b)
            if bdata:
                rates.append(bdata["correctness_rate"])
        if rates:
            avg_rate = statistics.fmean(rates)
            lines.append(f"| {backend_labels[b]} | {avg_rate:.0%} |")

    lines.extend(
        [
            "",
            "## Trace details",
            "",
        ]
    )

    for trace_data in payload["traces"]:
        trace_id = trace_data["trace_id"]
        shape = trace_data["tags"].get("shape", "")
        fixture = trace_data["fixture_id"]
        lines.extend(
            [
                f"### `{trace_id}`",
                "",
                f"Shape: {shape} \u00b7 Fixture: `{fixture}` \u00b7 Steps: {trace_data['step_count']}",
                "",
                "| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for b in backend_order:
            bdata = trace_data["backends"].get(b)
            if bdata:
                lines.append(
                    f"| {backend_labels[b]} "
                    f"| {bdata['median_total_ms']:.1f} "
                    f"| {bdata['mean_total_ms']:.1f} "
                    f"| {bdata['min_total_ms']:.1f} "
                    f"| {bdata['max_total_ms']:.1f} "
                    f"| {bdata['correctness_rate']:.0%} |"
                )
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- These numbers come from the benchmark VM and should be treated as "
            "comparative, not absolute throughput guarantees.",
            "- The built-in filesystem backend is the local baseline; the remote backends "
            "trade latency for different persistence semantics.",
            f"- Raw machine-readable results live in `{payload['results_path']}`.",
            "",
        ]
    )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-path",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Where to write the JSON benchmark results.",
    )
    parser.add_argument(
        "--readme-path",
        type=Path,
        default=DEFAULT_README_PATH,
        help="Where to write the markdown report.",
    )
    parser.add_argument(
        "--measured-runs",
        type=int,
        default=MEASURED_RUNS,
        help="Measured repetitions per trace.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=WARMUP_RUNS,
        help="Warmup repetitions per trace.",
    )
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Start and stop the local benchmark services with docker compose.",
    )
    parser.add_argument(
        "--write-readme",
        action="store_true",
        help="Write the markdown report after the benchmark run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex[:12]
    results_path = args.results_path
    readme_path = args.readme_path
    results_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.parent.mkdir(parents=True, exist_ok=True)

    if args.manage_services:
        run_compose(
            "up",
            "-d",
            "--wait",
            "minio",
            "postgres",
            "azurite",
            "fake-gcs-server",
            "mongodb",
            "valkey"
        )

    try:
        realistic_traces = [t for t in TRACES if t.suite == "realistic"]
        adapters = build_async_adapters(run_id)
        all_results = asyncio.run(
            run_all_async(
                adapters,
                realistic_traces,
                run_id=run_id,
                warmup_runs=args.warmup_runs,
                measured_runs=args.measured_runs,
            )
        )

        payload = build_payload(
            run_id=run_id,
            results=all_results,
            measured_runs=args.measured_runs,
            warmup_runs=args.warmup_runs,
            managed_services=args.manage_services,
            results_path=results_path,
        )
        results_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        if args.write_readme:
            readme_path.write_text(build_markdown_report(payload) + "\n", encoding="utf-8")
    finally:
        if args.manage_services:
            run_compose("down", "-v")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
