"""
perf_test.py — API response time benchmarks for the GBF Dashboard.

Hits each endpoint type and reports min/mean/p95/max latency.
Requires the backend to be running (default: http://localhost:8000).

Usage:
    python scripts/perf_test.py [--base-url http://localhost:8000] [--reps 10]
"""
import argparse
import statistics
import time
from dataclasses import dataclass, field

import urllib.request
import urllib.error


@dataclass
class Result:
    name:    str
    times:   list[float] = field(default_factory=list)
    errors:  int = 0

    @property
    def ok(self):            return len(self.times)
    @property
    def mean(self):          return statistics.mean(self.times)   if self.times else None
    @property
    def p95(self):
        if len(self.times) < 2: return self.times[0] if self.times else None
        return sorted(self.times)[int(len(self.times) * 0.95)]
    @property
    def minimum(self):       return min(self.times)               if self.times else None
    @property
    def maximum(self):       return max(self.times)               if self.times else None


ENDPOINTS = [
    # (name, path, budget_ms)
    ("health",              "/api/health",                                           50),
    ("players_list",        "/api/players?limit=20",                                100),
    ("player_profile",      "/api/players/Alice/profile",                           100),
    ("heatmap_global",      "/api/heatmap/cube-error",                               50),
    ("heatmap_by_length",   "/api/heatmap/cube-error?match_length=7",                50),
    ("heatmap_cell",        "/api/heatmap/cube-error/cell?away_p1=3&away_p2=3",      50),
    ("positions_filtered",  "/api/positions?away_p1=3&away_p2=3&limit=50",          500),
    ("positions_blunders",  "/api/positions?blunders_only=true&limit=50",           500),
    ("cube_thresholds",     "/api/cube/thresholds",                                  20),
    ("cube_recommendation", "/api/cube/recommendation?away_p1=3&away_p2=3&cube_value=1&equity=0.1&gammon_threat=0.1", 20),
    ("stats_overview",      "/api/stats/overview",                                   50),
    ("stats_rankings",      "/api/stats/rankings?metric=pr&limit=50",                50),
    ("stats_distribution",  "/api/stats/error-distribution",                        100),
    ("clusters_list",       "/api/clusters",                                         50),
    ("tournaments",         "/api/tournaments",                                      50),
    ("map_points",          "/api/map/points?x_min=-10&x_max=10&y_min=-10&y_max=10", 400),
]


def fetch(url: str) -> float:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return (time.perf_counter() - t0) * 1000  # ms


def run(base_url: str, reps: int) -> None:
    print(f"\nGBF Dashboard — API performance test")
    print(f"Base URL : {base_url}")
    print(f"Reps     : {reps}")
    print(f"{'Endpoint':<30} {'OK':>3} {'Err':>3} {'Min ms':>8} {'Mean ms':>8} {'P95 ms':>8} {'Max ms':>8} {'Budget':>8} {'Pass':>5}")
    print("─" * 95)

    all_pass = True
    for name, path, budget in ENDPOINTS:
        r = Result(name=name)
        url = base_url.rstrip("/") + path
        for _ in range(reps):
            try:
                r.times.append(fetch(url))
            except Exception:
                r.errors += 1

        passed = r.p95 is not None and r.p95 <= budget
        if not passed:
            all_pass = False
        mark = "✓" if passed else "✗"
        print(
            f"{name:<30} {r.ok:>3} {r.errors:>3} "
            f"{r.minimum or 0:>8.1f} {r.mean or 0:>8.1f} {r.p95 or 0:>8.1f} {r.maximum or 0:>8.1f} "
            f"{budget:>7}ms {mark:>5}"
        )

    print("─" * 95)
    print(f"Result: {'ALL PASS ✓' if all_pass else 'FAILURES DETECTED ✗'}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GBF API performance test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--reps", type=int, default=5)
    args = parser.parse_args()
    run(args.base_url, args.reps)
