#!/usr/bin/env python3
"""Build a deduplicated source manifest for .xg files before pipeline export.

Scans all .xg files in a directory, hashes each one with xxhash64 (very fast),
groups by hash, and writes one canonical path per unique file to a manifest.

Reduces export work by the duplication factor (BMAB = 5×).

Usage:
    python scripts/build_source_manifest.py \\
        --xg-dir data/bmab-2025-06-23 \\
        --output data/source_manifest.txt \\
        [--workers 8]

Output:
    data/source_manifest.txt   — one absolute path per line (canonical files)
    stdout                     — duplication report
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import xxhash


def hash_file(path: str) -> tuple[str, str]:
    """Return (path, xxhash64 hex) for a single file."""
    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 20)  # 1 MB chunks
            if not block:
                break
            h.update(block)
    return path, h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deduplicated source manifest for .xg files"
    )
    parser.add_argument("--xg-dir",  required=True, help="Directory containing .xg files")
    parser.add_argument("--output",  required=True, help="Output manifest file path")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel workers for hashing (default: 8)")
    args = parser.parse_args()

    xg_dir = Path(args.xg_dir)
    if not xg_dir.exists():
        print(f"ERROR: {xg_dir} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {xg_dir} for .xg files ...")
    t0 = time.time()
    all_files = sorted(str(p) for p in xg_dir.glob("*.xg"))
    n_total = len(all_files)
    if n_total == 0:
        print("No .xg files found.", file=sys.stderr)
        sys.exit(1)
    print(f"  {n_total:,} files found")

    # Hash all files in parallel
    print(f"  Hashing with {args.workers} workers ...")
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
                print(f"  {done:,}/{n_total:,}  ({done/elapsed:.0f} files/s)", flush=True)

    elapsed = time.time() - t0
    print(f"  Hashing done in {elapsed:.1f}s")

    # Pick canonical file per group (alphabetically first = smallest prefix)
    canonical: list[str] = []
    for digest, paths in hash_to_files.items():
        canonical.append(sorted(paths)[0])
    canonical.sort()

    # Write manifest
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(canonical) + "\n")

    # Report
    n_unique   = len(canonical)
    dup_factor = n_total / n_unique if n_unique > 0 else 1
    n_skipped  = n_total - n_unique
    sizes      = [len(v) for v in hash_to_files.values()]
    max_dup    = max(sizes)
    n_singles  = sum(1 for s in sizes if s == 1)

    print(f"\n{'='*50}")
    print(f"  Source deduplication report")
    print(f"{'='*50}")
    print(f"  Total .xg files  : {n_total:,}")
    print(f"  Unique files     : {n_unique:,}")
    print(f"  Skipped          : {n_skipped:,}  ({100*n_skipped/n_total:.1f}%)")
    print(f"  Duplication factor: {dup_factor:.2f}×")
    print(f"  Max copies of one file: {max_dup}")
    print(f"  Files with no duplicate: {n_singles:,}")
    print(f"\n  Manifest written to: {out_path}")
    print(f"  Processing {n_unique:,} files instead of {n_total:,} saves "
          f"{dup_factor-1:.1f}× export time and disk space.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
