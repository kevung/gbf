#!/usr/bin/env python3
"""Build a source manifest for .xg files before pipeline export.

Two independent filters are applied:

  1. Deduplication  — files with identical content (same xxhash64) are
                      collapsed to one canonical path (alphabetically first).
                      BMAB has 5 exact copies per match: 166K → 33K files.
                      A dataset with no duplicates passes all files through.

  2. Already-done   — files whose hash appears in a processed-hashes journal
                      are skipped entirely (incremental processing).

The journal is updated by run_full_pipeline.sh after each batch completes,
so a crashed run can be safely resumed.

Usage
-----
    # First run (no journal yet):
    python scripts/build_source_manifest.py \\
        --xg-dir data/bmab-2025-06-23 \\
        --output data/parquet/.source_manifest.txt \\
        --journal data/parquet/.processed_hashes.txt

    # After adding new files to xg-dir:
    python scripts/build_source_manifest.py \\
        --xg-dir data/bmab-new \\
        --output data/parquet/.source_manifest.txt \\
        --journal data/parquet/.processed_hashes.txt
    # → only new/unseen files appear in the manifest

    # Mark all current manifest files as processed (called by pipeline):
    python scripts/build_source_manifest.py --mark-done \\
        --manifest data/parquet/.source_manifest.txt \\
        --journal  data/parquet/.processed_hashes.txt

Outputs
-------
    <output>  — one absolute path per line (files to export in next run)
    stdout    — duplication + already-done report
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import xxhash


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_file(path: str) -> tuple[str, str]:
    """Return (path, xxhash64 hex).  Reads in 1 MB chunks."""
    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            h.update(block)
    return path, h.hexdigest()


# ---------------------------------------------------------------------------
# Journal helpers
# ---------------------------------------------------------------------------

def load_journal(path: Path) -> set[str]:
    """Return set of already-processed xxhash64 hex digests."""
    if not path.exists():
        return set()
    return set(path.read_text().splitlines())


def append_journal(journal_path: Path, hashes: set[str]) -> None:
    """Append new hashes to the journal (create if missing)."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a") as fh:
        for h in sorted(hashes):
            fh.write(h + "\n")


# ---------------------------------------------------------------------------
# --mark-done mode
# ---------------------------------------------------------------------------

def mark_done(manifest_path: Path, journal_path: Path, workers: int) -> None:
    """Hash all files listed in manifest and add their hashes to journal."""
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    files = [l.strip() for l in manifest_path.read_text().splitlines() if l.strip()]
    if not files:
        print("Manifest is empty — nothing to mark.")
        return

    already = load_journal(journal_path)
    print(f"Marking {len(files):,} files as processed ...")
    t0 = time.time()
    new_hashes: set[str] = set()
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(hash_file, f): f for f in files}
        for fut in as_completed(futures):
            _, digest = fut.result()
            if digest not in already:
                new_hashes.add(digest)
            done += 1
            if done % 2000 == 0 or done == len(files):
                print(f"  {done:,}/{len(files):,}", flush=True)

    append_journal(journal_path, new_hashes)
    print(f"  +{len(new_hashes):,} new hashes added to journal "
          f"({len(already)+len(new_hashes):,} total) in {time.time()-t0:.1f}s")


# ---------------------------------------------------------------------------
# Main manifest-building mode
# ---------------------------------------------------------------------------

def build_manifest(args: argparse.Namespace) -> None:
    xg_dir      = Path(args.xg_dir)
    out_path    = Path(args.output)
    journal_path = Path(args.journal) if args.journal else None

    if not xg_dir.exists():
        print(f"ERROR: {xg_dir} not found", file=sys.stderr)
        sys.exit(1)

    # ── Scan source files ────────────────────────────────────────────
    print(f"Scanning {xg_dir} for .xg files ...")
    all_files = sorted(str(p) for p in xg_dir.glob("*.xg"))
    n_total = len(all_files)
    if n_total == 0:
        print("No .xg files found.", file=sys.stderr)
        sys.exit(1)
    print(f"  {n_total:,} .xg files found")

    # ── Load already-processed hashes ────────────────────────────────
    done_hashes: set[str] = set()
    if journal_path:
        done_hashes = load_journal(journal_path)
        if done_hashes:
            print(f"  Journal: {len(done_hashes):,} previously processed hashes")

    # ── Hash all files in parallel ───────────────────────────────────
    print(f"  Hashing with {args.workers} workers ...")
    t0 = time.time()
    hash_to_files: dict[str, list[str]] = defaultdict(list)
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(hash_file, f): f for f in all_files}
        for fut in as_completed(futures):
            path, digest = fut.result()
            hash_to_files[digest].append(path)
            done += 1
            if done % 5000 == 0 or done == n_total:
                elapsed = time.time() - t0
                print(f"  {done:,}/{n_total:,}  ({done/elapsed:.0f} files/s)",
                      flush=True)
    print(f"  Hashing done in {time.time()-t0:.1f}s")

    # ── Apply filters ────────────────────────────────────────────────
    n_already_done = 0
    n_dup_skipped  = 0
    canonical: list[str] = []

    all_sizes = [len(v) for v in hash_to_files.values()]

    for digest, paths in hash_to_files.items():
        # Filter 1: already processed
        if digest in done_hashes:
            n_already_done += len(paths)
            continue
        # Filter 2: deduplication — keep alphabetically first
        n_dup_skipped += len(paths) - 1
        canonical.append(sorted(paths)[0])

    canonical.sort()

    # ── Write manifest ───────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(canonical) + "\n" if canonical else "")

    # ── Report ───────────────────────────────────────────────────────
    n_unique   = len(set(hash_to_files.keys()) - done_hashes)
    n_to_export = len(canonical)
    dup_factor = (
        (n_total - n_already_done) / max(n_unique, 1)
        if n_unique else 1.0
    )
    n_singles  = sum(1 for s in all_sizes if s == 1)
    max_dup    = max(all_sizes) if all_sizes else 0

    print(f"\n{'='*54}")
    print(f"  Source manifest report")
    print(f"{'='*54}")
    print(f"  Total .xg files found   : {n_total:,}")
    if done_hashes:
        print(f"  Already processed       : {n_already_done:,}  (skipped)")
    print(f"  Duplicate copies skipped: {n_dup_skipped:,}")
    if dup_factor > 1.01:
        print(f"  Duplication factor      : {dup_factor:.2f}×  "
              f"(max {max_dup} copies of one file)")
    else:
        print(f"  Duplication             : none detected  "
              f"(all {n_singles:,} files are unique)")
    print(f"  → Files to export       : {n_to_export:,}")
    print(f"\n  Manifest written to: {out_path}")
    if journal_path:
        print(f"  Journal           : {journal_path}  "
              f"({len(done_hashes):,} entries)")
    print(f"{'='*54}")

    if n_to_export == 0:
        print("\n  All files already processed — nothing to do.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deduplicated source manifest for .xg pipeline export"
    )
    sub = parser.add_subparsers(dest="cmd")

    # Default (no subcommand) = build manifest
    parser.add_argument("--xg-dir",  help="Directory containing .xg files")
    parser.add_argument("--output",  help="Output manifest file path")
    parser.add_argument("--journal", default=None,
                        help="Processed-hashes journal (optional)")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel hashing workers (default: 8)")

    # Subcommand: mark current manifest as done
    p_mark = sub.add_parser("mark-done",
                             help="Add manifest file hashes to the journal")
    p_mark.add_argument("--manifest", required=True)
    p_mark.add_argument("--journal",  required=True)
    p_mark.add_argument("--workers", type=int, default=8)

    args = parser.parse_args()

    if args.cmd == "mark-done":
        mark_done(Path(args.manifest), Path(args.journal), args.workers)
    else:
        if not args.xg_dir or not args.output:
            parser.error("--xg-dir and --output are required")
        build_manifest(args)


if __name__ == "__main__":
    main()
