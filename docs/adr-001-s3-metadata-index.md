# ADR-001: S3 metadata index / manifest for search and list scalability

**Status:** Rejected — defer indefinitely  
**Date:** 2026-04-15  
**Issues:** Depends on #14 (als\_info), #17 (agrep\_raw), #18 (aglob\_info)

---

## Context

After the simpler S3 optimisations in PRs #14, #17, and #18, a question
remains: would a hidden metadata index or manifest stored inside the S3
bucket provide additional scalability for `als_info`, `agrep_raw`, and
`aglob_info`?

A "hidden index" in this context means a special S3 object (e.g.
`.deepagents/index.json` or a set of per-prefix manifest objects) that
is maintained alongside the data files and contains a pre-built list of
keys, optionally with per-file metadata (size, modification time, content
snippets).  A "lock" would be required to serialise concurrent writers
that update the index.

---

## Options considered

### Option A — Prefix-only + targeted optimisations (already implemented)

**What was done (PRs #14 / #17 / #18):**

| Method | Before | After |
|--------|--------|-------|
| `als_info` | Recursive `list_objects_v2`, Python child-derivation | `Delimiter='/'` — one paginator call, zero GETs |
| `agrep_raw` | N `get_object` calls, separate sessions | Single session, glob pre-filter, then N GETs |
| `aglob_info` | Full-prefix listing, Python fnmatch | Literal pattern prefix narrows `_list_keys` |

**Cost:** Zero additional S3 objects, zero consistency concerns, zero write
amplification.

---

### Option B — Hidden flat manifest (e.g. `.deepagents/manifest.json`)

A single JSON object listing all keys with metadata.

**Benefits:**
- `als_info` / `aglob_info` could be answered with one GET instead of
  one paginator call.
- grep could scan only the manifest to identify candidates, then fetch
  only matching files.

**Costs:**

1. **Write amplification.** Every `awrite` / `aedit` now requires an
   additional GET + PUT on the manifest object.  For small files the
   manifest GET/PUT can cost more than the data write itself.

2. **Consistency.** S3 does not support atomic compare-and-swap on
   objects.  Two concurrent writers both doing GET → modify → PUT will
   silently lose one update (last-writer-wins).  Recovering from a
   corrupt manifest requires re-scanning the entire prefix.

3. **Locking complexity.** To prevent corruption a distributed lock is
   needed (e.g. a `.deepagents/lock` object used with conditional writes
   via `If-None-Match: *`).  This adds latency, retry logic, and a new
   failure mode (stale lock after crashed writer).

4. **Manifest growth.** In a bucket with millions of objects the manifest
   itself becomes a scalability bottleneck: every write blocks on
   deserialising and re-serialising the full manifest.

5. **Recovery.** If the manifest drifts from reality (crash, race, bug)
   the only safe remediation is a full re-scan, which is slower than
   simply not having a manifest.

---

### Option C — Per-prefix shard manifests

A manifest per "directory" (e.g. `.deepagents/shard/<prefix_hash>.json`).

**Benefits over Option B:**
- Smaller per-shard write amplification.
- Concurrent writes to different prefixes do not contend.

**Costs:**
- All costs from Option B still apply within a shard.
- Cross-prefix queries (e.g. `agrep_raw` over `/`) must still gather N
  shards.
- Introduces new operational complexity: shard discovery, empty-shard
  cleanup, cross-shard consistency.

---

## Assessment

The three simpler optimisations (PRs #14, #17, #18) already address the
root cause of the scalability concern:

- `als_info` now issues **one** paginator call with no GETs at all.
- `aglob_info` narrows the S3 listing to the literal pattern prefix.
- `agrep_raw` shares one session and pre-filters by filename before
  fetching.

A manifest would only help `agrep_raw` (avoiding N GETs) and only when
the regex matches a small fraction of a large result set where the
filenames cannot be filtered by glob.  That is a narrow scenario.

Against this narrow benefit, the manifest introduces:
- **Write amplification** on every mutation.
- **Consistency risk** under concurrent access — a risk with no simple
  mitigation short of a distributed lock.
- **Operational complexity**: manifest repair, shard management.

The "lock" concept deserves explicit attention.  A lock is **not
necessary** if the manifest is absent; it is **mandatory** if one
exists.  Given that the rest of the system does not require distributed
coordination, adding a lock specifically for the manifest is a poor
trade-off.

---

## Decision

**Reject** Options B and C.  Do not introduce a hidden metadata index or
manifest for S3.

The prefix-based optimisations shipped in PRs #14, #17, and #18 are
sufficient for the current scale.  If future profiling against real
workloads demonstrates that `agrep_raw` over very large prefixes (>10k
objects) remains a bottleneck after those optimisations, re-evaluate at
that time — but only after measuring, and only against a design that
avoids distributed locking.

---

## Follow-up

None required.  If evidence of a real bottleneck emerges, open a new
issue with profiling data and a concrete proposal that addresses the
consistency and lock concerns above.
