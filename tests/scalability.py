"""
Scalability test helpers: shared dataset shapes and acceptance thresholds.

These constants and generators define the canonical "large tree" used across
all backend performance regression tests.  Optimization PRs must not regress
the acceptance assertions defined here.

Dataset shapes
--------------
Two distinct sizes are defined so that unit tests (which use mocks and incur
no real I/O cost) can verify behaviour at a larger scale than integration tests
(which write to real MinIO / PostgreSQL instances and need to finish quickly).

* **Unit scale** – 200 flat files or 10 × 30 = 300 nested files.
* **Integration scale** – 25 flat files or 3 × 8 = 24 nested files.

Acceptance invariants
---------------------
These are the correctness properties that every optimized implementation must
preserve.  They are stated here as plain English so that regression test
assertions can cite them directly.

1. ``als_info(path)`` returns *only* the direct children of ``path``.
   Given N direct-children files (no sub-directories), len(result) == N, all
   entries have ``is_dir=False``.
   Given M direct sub-directories (no flat files at root), len(result) == M,
   all entries have ``is_dir=True``.

2. ``agrep_raw(pattern, path)`` returns *no false positives and no false
   negatives*.  Given a tree where exactly K files contain ``GREP_MATCH_LINE``
   and the rest contain ``GREP_NOMATCH_LINE``, ``len(result) == K``.

3. ``aglob_info(pattern, path)`` returns *only* the files whose relative path
   matches *pattern*.  Given exactly K files ending with ``GLOB_MATCH_SUFFIX``
   and the rest ending with ``GLOB_NOMATCH_SUFFIX``, ``len(result) == K`` when
   pattern is ``f"*{GLOB_MATCH_SUFFIX}"``.
"""

from __future__ import annotations

# ── Unit-test scale (mocked, no real I/O) ────────────────────────────────────

LARGE_FLAT_FILES: int = 200
"""Number of flat files directly under a single directory."""

LARGE_NESTED_DIRS: int = 10
"""Number of subdirectories in a nested tree."""

LARGE_NESTED_FILES_PER_DIR: int = 30
"""Files per subdirectory in a nested tree."""

LARGE_NESTED_TOTAL: int = LARGE_NESTED_DIRS * LARGE_NESTED_FILES_PER_DIR
"""Total file count across the nested tree (300)."""

# ── Integration-test scale (real I/O, kept CI-friendly) ──────────────────────

INTEGRATION_FLAT_FILES: int = 25
"""Flat file count used by integration-scale scalability tests."""

INTEGRATION_NESTED_DIRS: int = 3
"""Subdirectory count for integration-scale nested tree."""

INTEGRATION_FILES_PER_DIR: int = 8
"""Files per subdirectory for integration-scale nested tree."""

INTEGRATION_NESTED_TOTAL: int = INTEGRATION_NESTED_DIRS * INTEGRATION_FILES_PER_DIR
"""Total file count for integration-scale nested tree (24)."""

# ── Content / naming markers ──────────────────────────────────────────────────

GREP_MATCH_LINE: str = "SCALABILITY_GREP_NEEDLE_xK9mQ"
"""Unique line present in every file that *should* be returned by agrep_raw."""

GREP_NOMATCH_LINE: str = "scalability_no_match_content"
"""Content in files that must *not* match the grep pattern."""

GLOB_MATCH_SUFFIX: str = "scalability_match.txt"
"""Filename suffix used for files that glob patterns should include."""

GLOB_NOMATCH_SUFFIX: str = "scalability_skip.log"
"""Filename suffix used for files that glob patterns should exclude."""

# ── Dataset path generators ───────────────────────────────────────────────────


def flat_file_paths(root: str = "/large_flat", n: int = LARGE_FLAT_FILES) -> list[str]:
    """Return *n* flat file paths directly under *root* (no sub-directories)."""
    root = root.rstrip("/")
    return [f"{root}/file_{i:04d}.txt" for i in range(n)]


def nested_tree_paths(
    root: str = "/large_nested",
    n_dirs: int = LARGE_NESTED_DIRS,
    files_per_dir: int = LARGE_NESTED_FILES_PER_DIR,
) -> list[str]:
    """Return all file paths in a two-level nested tree under *root*.

    The tree has *n_dirs* subdirectories each containing *files_per_dir*
    files, for a total of ``n_dirs * files_per_dir`` paths.
    """
    root = root.rstrip("/")
    paths: list[str] = []
    for d in range(n_dirs):
        for f in range(files_per_dir):
            paths.append(f"{root}/dir_{d:03d}/file_{f:04d}.txt")
    return paths


def grep_dataset_paths(
    root: str = "/large_grep",
    n_matching: int = 50,
    n_total: int = LARGE_NESTED_TOTAL,
) -> tuple[list[str], list[str]]:
    """Return ``(matching_paths, all_paths)`` for a grep scenario.

    The first *n_matching* paths are the ones whose content contains
    ``GREP_MATCH_LINE``; the rest contain ``GREP_NOMATCH_LINE``.
    """
    root = root.rstrip("/")
    all_paths = [f"{root}/file_{i:04d}.txt" for i in range(n_total)]
    return all_paths[:n_matching], all_paths


def glob_dataset_paths(
    root: str = "/large_glob",
    n_matching: int = 40,
    n_total: int = LARGE_NESTED_TOTAL,
) -> tuple[list[str], list[str]]:
    """Return ``(matching_paths, all_paths)`` for a glob scenario.

    Matching files end with ``GLOB_MATCH_SUFFIX``; the rest end with
    ``GLOB_NOMATCH_SUFFIX``.
    """
    root = root.rstrip("/")
    matching = [f"{root}/file_{i:04d}_{GLOB_MATCH_SUFFIX}" for i in range(n_matching)]
    others = [
        f"{root}/file_{i:04d}_{GLOB_NOMATCH_SUFFIX}"
        for i in range(n_matching, n_total)
    ]
    return matching, matching + others
