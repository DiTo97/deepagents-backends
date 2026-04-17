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
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import aioboto3
from deepagents.backends import FilesystemBackend

from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config

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
WARMUP_RUNS = 1
MEASURED_RUNS = 5
MATCH_NEEDLE = "BENCHMARK_MATCH_NEEDLE_9fC3"


@dataclass(frozen=True)
class ScenarioConfig:
    """Benchmark scenario definition."""

    name: str
    description: str
    operation: str
    extra: dict[str, Any]


SCENARIOS = [
    ScenarioConfig(
        name="write_small_text",
        description="Create a new 40-line text file in a nested directory.",
        operation="write",
        extra={},
    ),
    ScenarioConfig(
        name="read_medium_text",
        description="Read a pre-populated 200-line text file.",
        operation="read",
        extra={"lines": 200},
    ),
    ScenarioConfig(
        name="edit_medium_text",
        description="Replace one marker inside a pre-populated 200-line text file.",
        operation="edit",
        extra={"lines": 200},
    ),
    ScenarioConfig(
        name="ls_flat_directory",
        description="List a directory containing 100 direct child files.",
        operation="ls",
        extra={"files": 100},
    ),
    ScenarioConfig(
        name="glob_nested_python",
        description="Glob for Python files inside a 5x12 nested tree plus 25 non-matches.",
        operation="glob",
        extra={"dirs": 5, "matches_per_dir": 12, "non_matches": 25},
    ),
    ScenarioConfig(
        name="grep_nested_literal",
        description="Search for a literal needle across 80 files with 20 matches.",
        operation="grep",
        extra={"total_files": 80, "matching_files": 20},
    ),
    ScenarioConfig(
        name="upload_binary_batch",
        description="Upload a batch of 20 binary files (4 KiB each).",
        operation="upload",
        extra={"files": 20, "bytes_per_file": 4096},
    ),
    ScenarioConfig(
        name="download_binary_batch",
        description="Download a batch of 20 pre-populated binary files (4 KiB each).",
        operation="download",
        extra={"files": 20, "bytes_per_file": 4096},
    ),
]


@dataclass
class ScenarioResult:
    """Measured timings for a scenario/backend pair."""

    scenario: str
    description: str
    backend: str
    samples_ms: list[float]
    median_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float


class BenchmarkBackend(Protocol):
    """Backend adapter used by the benchmark runner."""

    name: str

    def setup(self) -> None: ...

    def teardown(self) -> None: ...

    def write_text(self, path: str, content: str) -> None: ...

    def read_text(self, path: str) -> str: ...

    def edit_text(self, path: str, old: str, new: str) -> int: ...

    def list_entries(self, path: str) -> list[dict[str, Any]]: ...

    def glob_paths(self, pattern: str, path: str) -> list[dict[str, Any]]: ...

    def grep_matches(
        self, pattern: str, path: str, glob_pattern: str | None = None
    ) -> list[dict[str, Any]]: ...

    def upload_bytes(self, files: list[tuple[str, bytes]]) -> None: ...

    def download_bytes(self, paths: list[str]) -> list[bytes]: ...


def make_text_document(lines: int, *, marker: str = "payload") -> str:
    """Create deterministic benchmark text content."""

    return "\n".join(f"{marker} line {index:04d}" for index in range(lines))


def make_binary_payload(size: int) -> bytes:
    """Create deterministic binary content."""

    return (b"benchmark-bytes-" * ((size // 16) + 1))[:size]


class FilesystemAdapter:
    """Adapter for deepagents' built-in FilesystemBackend."""

    name = "filesystem"

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.backend = FilesystemBackend(root_dir=runtime_dir, virtual_mode=True)

    def setup(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def teardown(self) -> None:
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def write_text(self, path: str, content: str) -> None:
        result = self.backend.write(path, content)
        if result.error:
            raise RuntimeError(result.error)

    def read_text(self, path: str) -> str:
        result = self.backend.read(path)
        if result.error:
            raise RuntimeError(result.error)
        if result.file_data is None:
            raise RuntimeError(f"Missing file data for {path}")
        if isinstance(result.file_data, dict):
            return str(result.file_data["content"])
        return str(result.file_data.content)

    def edit_text(self, path: str, old: str, new: str) -> int:
        result = self.backend.edit(path, old, new)
        if result.error:
            raise RuntimeError(result.error)
        return int(result.occurrences or 0)

    def list_entries(self, path: str) -> list[dict[str, Any]]:
        result = self.backend.ls(path)
        if result.error:
            raise RuntimeError(result.error)
        return list(result.entries or [])

    def glob_paths(self, pattern: str, path: str) -> list[dict[str, Any]]:
        result = self.backend.glob(pattern, path)
        if result.error:
            raise RuntimeError(result.error)
        return list(result.matches or [])

    def grep_matches(
        self, pattern: str, path: str, glob_pattern: str | None = None
    ) -> list[dict[str, Any]]:
        result = self.backend.grep(pattern, path, glob_pattern)
        if result.error:
            raise RuntimeError(result.error)
        return list(result.matches or [])

    def upload_bytes(self, files: list[tuple[str, bytes]]) -> None:
        responses = self.backend.upload_files(files)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))

    def download_bytes(self, paths: list[str]) -> list[bytes]:
        responses = self.backend.download_files(paths)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))
        return [response.content or b"" for response in responses]


class S3Adapter:
    """Adapter for the MinIO-backed S3 backend."""

    name = "minio_s3"

    def __init__(self, prefix: str) -> None:
        self.backend = S3Backend(
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

    def setup(self) -> None:
        asyncio.run(ensure_minio_bucket())

    def teardown(self) -> None:
        pass

    def write_text(self, path: str, content: str) -> None:
        result = self.backend.write(path, content)
        if result.error:
            raise RuntimeError(result.error)

    def read_text(self, path: str) -> str:
        result = self.backend.read(path)
        if result.startswith("Error:"):
            raise RuntimeError(result)
        return result

    def edit_text(self, path: str, old: str, new: str) -> int:
        result = self.backend.edit(path, old, new)
        if result.error:
            raise RuntimeError(result.error)
        return int(result.occurrences or 0)

    def list_entries(self, path: str) -> list[dict[str, Any]]:
        return self.backend.ls_info(path)

    def glob_paths(self, pattern: str, path: str) -> list[dict[str, Any]]:
        return self.backend.glob_info(pattern, path)

    def grep_matches(
        self, pattern: str, path: str, glob_pattern: str | None = None
    ) -> list[dict[str, Any]]:
        result = self.backend.grep_raw(pattern, path, glob_pattern)
        if isinstance(result, str):
            raise RuntimeError(result)
        return list(result)

    def upload_bytes(self, files: list[tuple[str, bytes]]) -> None:
        responses = self.backend.upload_files(files)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))

    def download_bytes(self, paths: list[str]) -> list[bytes]:
        responses = self.backend.download_files(paths)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))
        return [response.content or b"" for response in responses]


class PostgresAdapter:
    """Adapter for the PostgreSQL backend."""

    name = "postgres"

    def __init__(self, table: str) -> None:
        self.backend = PostgresBackend(
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

    def setup(self) -> None:
        asyncio.run(self.backend.initialize())

    def teardown(self) -> None:
        try:
            asyncio.run(self.backend.close())
        except asyncio.CancelledError:
            pass

    def write_text(self, path: str, content: str) -> None:
        result = self.backend.write(path, content)
        if result.error:
            raise RuntimeError(result.error)

    def read_text(self, path: str) -> str:
        result = self.backend.read(path)
        if result.startswith("Error:"):
            raise RuntimeError(result)
        return result

    def edit_text(self, path: str, old: str, new: str) -> int:
        result = self.backend.edit(path, old, new)
        if result.error:
            raise RuntimeError(result.error)
        return int(result.occurrences or 0)

    def list_entries(self, path: str) -> list[dict[str, Any]]:
        return self.backend.ls_info(path)

    def glob_paths(self, pattern: str, path: str) -> list[dict[str, Any]]:
        return self.backend.glob_info(pattern, path)

    def grep_matches(
        self, pattern: str, path: str, glob_pattern: str | None = None
    ) -> list[dict[str, Any]]:
        result = self.backend.grep_raw(pattern, path, glob_pattern)
        if isinstance(result, str):
            raise RuntimeError(result)
        return list(result)

    def upload_bytes(self, files: list[tuple[str, bytes]]) -> None:
        responses = self.backend.upload_files(files)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))

    def download_bytes(self, paths: list[str]) -> list[bytes]:
        responses = self.backend.download_files(paths)
        errors = [response for response in responses if response.error]
        if errors:
            raise RuntimeError(str(errors))
        return [response.content or b"" for response in responses]


async def ensure_minio_bucket() -> None:
    """Create the benchmark bucket if needed."""

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


def run_compose(*args: str) -> None:
    """Run docker compose against the repository compose file."""

    subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        check=True,
    )


def prepare_write(adapter: BenchmarkBackend, root: str, _: ScenarioConfig) -> tuple[str, str]:
    """Prepare the write scenario."""

    return (f"{root}/docs/generated.txt", make_text_document(40, marker="write"))


def run_write(adapter: BenchmarkBackend, context: tuple[str, str]) -> None:
    """Run the write scenario."""

    path, content = context
    adapter.write_text(path, content)


def prepare_read(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> str:
    """Prepare the read scenario."""

    path = f"{root}/docs/reference.txt"
    adapter.write_text(path, make_text_document(int(scenario.extra["lines"]), marker="read"))
    return path


def run_read(adapter: BenchmarkBackend, path: str) -> None:
    """Run the read scenario."""

    content = adapter.read_text(path)
    if "read line 0000" not in content:
        raise RuntimeError("Read verification failed")


def prepare_edit(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> tuple[str, str, str]:
    """Prepare the edit scenario."""

    path = f"{root}/docs/editable.txt"
    old = "TARGET_TOKEN"
    new = "UPDATED_TOKEN"
    content = "\n".join(
        [f"edit line {index:04d}" for index in range(int(scenario.extra["lines"]) - 1)] + [old]
    )
    adapter.write_text(path, content)
    return (path, old, new)


def run_edit(adapter: BenchmarkBackend, context: tuple[str, str, str]) -> None:
    """Run the edit scenario."""

    path, old, new = context
    occurrences = adapter.edit_text(path, old, new)
    if occurrences != 1:
        raise RuntimeError(f"Expected one edit occurrence, got {occurrences}")


def prepare_ls(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> tuple[str, int]:
    """Prepare the list-directory scenario."""

    directory = f"{root}/flat"
    total_files = int(scenario.extra["files"])
    for index in range(total_files):
        adapter.write_text(f"{directory}/file_{index:04d}.txt", "ls payload")
    return (directory, total_files)


def run_ls(adapter: BenchmarkBackend, context: tuple[str, int]) -> None:
    """Run the list-directory scenario."""

    directory, expected_count = context
    entries = adapter.list_entries(directory)
    if len(entries) != expected_count:
        raise RuntimeError(f"Expected {expected_count} entries, got {len(entries)}")


def prepare_glob(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> tuple[str, int]:
    """Prepare the glob scenario."""

    search_root = f"{root}/tree"
    expected = 0
    for directory_index in range(int(scenario.extra["dirs"])):
        for file_index in range(int(scenario.extra["matches_per_dir"])):
            adapter.write_text(
                f"{search_root}/pkg_{directory_index:02d}/module_{file_index:02d}.py",
                "print('glob')",
            )
            expected += 1
    for file_index in range(int(scenario.extra["non_matches"])):
        adapter.write_text(
            f"{search_root}/pkg_misc/asset_{file_index:02d}.txt",
            "not a python file",
        )
    return (search_root, expected)


def run_glob(adapter: BenchmarkBackend, context: tuple[str, int]) -> None:
    """Run the glob scenario."""

    search_root, expected = context
    matches = adapter.glob_paths("**/*.py", search_root)
    if len(matches) != expected:
        raise RuntimeError(f"Expected {expected} glob matches, got {len(matches)}")


def prepare_grep(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> tuple[str, int]:
    """Prepare the grep scenario."""

    search_root = f"{root}/search"
    total_files = int(scenario.extra["total_files"])
    matching_files = int(scenario.extra["matching_files"])
    for index in range(total_files):
        content = MATCH_NEEDLE if index < matching_files else "plain content"
        adapter.write_text(f"{search_root}/note_{index:04d}.txt", content)
    return (search_root, matching_files)


def run_grep(adapter: BenchmarkBackend, context: tuple[str, int]) -> None:
    """Run the grep scenario."""

    search_root, expected = context
    matches = adapter.grep_matches(MATCH_NEEDLE, search_root, "*.txt")
    if len(matches) != expected:
        raise RuntimeError(f"Expected {expected} grep matches, got {len(matches)}")


def prepare_upload(
    adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig
) -> list[tuple[str, bytes]]:
    """Prepare the upload scenario."""

    payload = make_binary_payload(int(scenario.extra["bytes_per_file"]))
    total_files = int(scenario.extra["files"])
    return [
        (f"{root}/uploads/blob_{index:04d}.bin", payload)
        for index in range(total_files)
    ]


def run_upload(adapter: BenchmarkBackend, files: list[tuple[str, bytes]]) -> None:
    """Run the upload scenario."""

    adapter.upload_bytes(files)


def prepare_download(adapter: BenchmarkBackend, root: str, scenario: ScenarioConfig) -> list[str]:
    """Prepare the download scenario."""

    files = prepare_upload(adapter, root, scenario)
    adapter.upload_bytes(files)
    return [path for path, _ in files]


def run_download(adapter: BenchmarkBackend, paths: list[str]) -> None:
    """Run the download scenario."""

    content = adapter.download_bytes(paths)
    if len(content) != len(paths):
        raise RuntimeError(f"Expected {len(paths)} downloads, got {len(content)}")


PREPARE_HANDLERS = {
    "write": prepare_write,
    "read": prepare_read,
    "edit": prepare_edit,
    "ls": prepare_ls,
    "glob": prepare_glob,
    "grep": prepare_grep,
    "upload": prepare_upload,
    "download": prepare_download,
}

RUN_HANDLERS = {
    "write": run_write,
    "read": run_read,
    "edit": run_edit,
    "ls": run_ls,
    "glob": run_glob,
    "grep": run_grep,
    "upload": run_upload,
    "download": run_download,
}


def build_backend_adapters(run_id: str) -> list[BenchmarkBackend]:
    """Create benchmark adapters."""

    table_suffix = hashlib.sha1(run_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return [
        FilesystemAdapter(Path("/tmp") / "deepagents-backends-benchmark" / run_id / "filesystem"),
        PostgresAdapter(f"benchmark_{table_suffix}"),
        S3Adapter(f"benchmark/{run_id}/minio"),
    ]


def benchmark_backend(
    adapter: BenchmarkBackend,
    *,
    run_id: str,
    measured_runs: int,
    warmup_runs: int,
) -> list[ScenarioResult]:
    """Run all scenarios for one backend adapter."""

    results: list[ScenarioResult] = []
    adapter.setup()
    try:
        for scenario in SCENARIOS:
            samples_ms: list[float] = []
            prepare = PREPARE_HANDLERS[scenario.operation]
            run = RUN_HANDLERS[scenario.operation]
            total_runs = warmup_runs + measured_runs
            for iteration in range(total_runs):
                root = f"/{run_id}/{scenario.name}/iteration_{iteration:02d}"
                context = prepare(adapter, root, scenario)
                started = time.perf_counter_ns()
                run(adapter, context)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                if iteration >= warmup_runs:
                    samples_ms.append(elapsed_ms)

            results.append(
                ScenarioResult(
                    scenario=scenario.name,
                    description=scenario.description,
                    backend=adapter.name,
                    samples_ms=samples_ms,
                    median_ms=statistics.median(samples_ms),
                    mean_ms=statistics.fmean(samples_ms),
                    min_ms=min(samples_ms),
                    max_ms=max(samples_ms),
                )
            )
    finally:
        adapter.teardown()
    return results


def build_markdown_report(payload: dict[str, Any]) -> str:
    """Render the benchmark report README."""

    scenarios = payload["scenarios"]
    environment = payload["environment"]
    lines = [
        "# Benchmark Results",
        "",
        "This folder contains a reproducible benchmark for three file-oriented backends:",
        "",
        (
            "- `FilesystemBackend` from `deepagents`, scoped to a dedicated root "
            "directory with `virtual_mode=True`."
        ),
        "- `PostgresBackend` from this repository, backed by Dockerized PostgreSQL.",
        "- `S3Backend` from this repository, backed by Dockerized MinIO.",
        "",
        "## How to run",
        "",
        "```bash",
        "export PATH=\"$HOME/.local/bin:$PATH\"",
        "cd /home/runner/work/deepagents-backends/deepagents-backends",
        "uv run python benchmark/run.py --manage-services --write-readme",
        "```",
        "",
        "## Methodology",
        "",
        f"- Warmup runs per scenario: `{payload['warmup_runs']}`",
        f"- Measured runs per scenario: `{payload['measured_runs']}`",
        "- Timings measure only the target operation; dataset setup is excluded.",
        (
            "- Filesystem paths are scoped to a dedicated benchmark root, so "
            "agent-visible paths stay within that root."
        ),
        (
            "- PostgreSQL uses a dedicated benchmark table per run; MinIO uses "
            "a dedicated object prefix per run."
        ),
        "",
        "## Environment",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Python: `{environment['python_version']}`",
        f"- Platform: `{environment['platform']}`",
        f"- Machine: `{environment['machine']}`",
        f"- Docker managed by script: `{payload['managed_services']}`",
        "",
        "## Median latency by scenario",
        "",
        "| Scenario | Filesystem (ms) | PostgreSQL (ms) | MinIO S3 (ms) | Fastest |",
        "|---|---:|---:|---:|---|",
    ]

    backend_order = ["filesystem", "postgres", "minio_s3"]
    backend_labels = {
        "filesystem": "Filesystem",
        "postgres": "PostgreSQL",
        "minio_s3": "MinIO S3",
    }
    for scenario in scenarios:
        medians = {
            result["backend"]: result["median_ms"]
            for result in scenario["results"]
        }
        fastest_backend = min(medians, key=medians.get)
        lines.append(
            "| "
            f"`{scenario['name']}` | "
            f"{medians['filesystem']:.3f} | "
            f"{medians['postgres']:.3f} | "
            f"{medians['minio_s3']:.3f} | "
            f"{backend_labels[fastest_backend]} |"
        )

    lines.extend(
        [
            "",
            "## Scenario details",
            "",
        ]
    )

    for scenario in scenarios:
        lines.extend(
            [
                f"### `{scenario['name']}`",
                "",
                scenario["description"],
                "",
                "| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        ordered_results = sorted(
            scenario["results"],
            key=lambda item: backend_order.index(item["backend"]),
        )
        for result in ordered_results:
            samples = ", ".join(f"{sample:.3f}" for sample in result["samples_ms"])
            lines.append(
                "| "
                f"{backend_labels[result['backend']]} | "
                f"{result['median_ms']:.3f} | "
                f"{result['mean_ms']:.3f} | "
                f"{result['min_ms']:.3f} | "
                f"{result['max_ms']:.3f} | "
                f"{samples} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            (
                "- These numbers come from this sandbox VM and should be treated "
                "as comparative, not absolute throughput guarantees."
            ),
            (
                "- The built-in filesystem backend is fastest for local "
                "single-host access, while PostgreSQL and MinIO trade latency "
                "for remote persistence semantics."
            ),
            f"- Raw machine-readable results live in `{payload['results_path']}`.",
            "",
        ]
    )

    return "\n".join(lines)


def build_payload(
    *,
    run_id: str,
    results: list[ScenarioResult],
    measured_runs: int,
    warmup_runs: int,
    managed_services: bool,
    results_path: Path,
) -> dict[str, Any]:
    """Convert benchmark data into the persisted report format."""

    grouped: dict[str, list[ScenarioResult]] = {}
    for result in results:
        grouped.setdefault(result.scenario, []).append(result)
    try:
        results_path_display = str(results_path.relative_to(REPO_ROOT))
    except ValueError:
        results_path_display = str(results_path)

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
        "scenarios": [
            {
                "name": scenario.name,
                "description": scenario.description,
                "operation": scenario.operation,
                "extra": scenario.extra,
                "results": [asdict(item) for item in grouped[scenario.name]],
            }
            for scenario in SCENARIOS
        ],
    }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

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
        help="Measured repetitions per scenario.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=WARMUP_RUNS,
        help="Warmup repetitions per scenario.",
    )
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Start and stop PostgreSQL and MinIO with docker compose.",
    )
    parser.add_argument(
        "--write-readme",
        action="store_true",
        help="Write the markdown report after the benchmark run.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the benchmark suite."""

    args = parse_args()
    run_id = uuid.uuid4().hex[:12]
    results_path = args.results_path
    readme_path = args.readme_path
    results_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.parent.mkdir(parents=True, exist_ok=True)

    if args.manage_services:
        run_compose("up", "-d", "--wait", "minio", "postgres")

    try:
        all_results: list[ScenarioResult] = []
        for adapter in build_backend_adapters(run_id):
            all_results.extend(
                benchmark_backend(
                    adapter,
                    run_id=run_id,
                    measured_runs=args.measured_runs,
                    warmup_runs=args.warmup_runs,
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
