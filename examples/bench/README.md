# Bench example: a representative suite for comparing execution modes

The demo and containers examples show *mechanics*; this one is shaped for
*measurement*. It approximates how real suites actually look — many files
with lopsided runtimes, expensive lanes paying a fixed per-process
environment cost — at ~115 seconds of linear (single-process) time:

| Lane | Files | Test time | Simulated spin-up | Serial |
|---|---:|---:|---:|---:|
| `db_tests` | 6 | 56s (lopsided: 18s..4s per file) | 6s | 62s |
| `api_tests` | 3 | 19s | 3s | 22s |
| `unit_tests` | 8 | 30s (many small files) | — | 30s |

The spin-up is a session-scoped autouse fixture per lane directory: every
*process* that runs tests from that directory pays it once — a lane child
once, each lane shard again, and every xdist worker that touches the
directory pays its own copy. That is exactly the fixed-cost profile the
modes differ on. Tests are plain sleeps and fully concurrency-safe by
construction, so every mode completes — this example isolates scheduling,
not safety (see `examples/containers` for what shared state does to
per-test distribution).

## Run it

```bash
cd examples/bench
python bench.py            # 5 modes x (1 warm-up + 3 timed rounds)
python bench.py --runs 1   # quicker look
```

Modes compared: `serial`, `xdist-load` (`-n auto`), `xdist-loadfile`,
`lanes` (plain three-lane config), and `lanes-opt` — the optimized
config: `divisible = files` on the db lane (shard planning from recorded
durations) plus `lane_numprocesses = 4` on the unit lane (in-lane xdist).

The warm-up run doubles as the measurement pass: it records per-file
durations into `.pytest_cache/v/pytest-lanes/`, which is what lets the
optimized mode's shard planner fire in the timed rounds. First-ever runs
never shard — no data, no split.

## What to expect

With `db_tests` at 62s against a 30s second-longest lane, plain lanes are
bounded by the db lane. The optimized config attacks both terms of the
ceiling `min(T/2, D1 - D2)`: in-lane xdist shrinks the unit lane, and
sharding halves the db lane's test time for one extra 6s spin-up.

Measured 2026-07-24 (Ryzen 5 7600, 6C/12T, medians of 3 rounds):

| Mode | Median |
|---|---:|
| serial | 114.5s |
| xdist `-n auto` | 24.9s |
| xdist `-n auto --dist loadfile` | 32.9s |
| lanes (plain) | 68.0s |
| **lanes-opt** | **39.1s** |

Read it honestly: the optimized config cuts plain lanes by 1.74x, and raw
xdist still wins here — this suite is 100% concurrency-safe sleeps, which
is xdist's best case and nobody's real codebase. The interesting rows for
real suites are lanes vs lanes-opt (what the optimizations buy) and the
`examples/containers` example (what shared state does to xdist). Exact
numbers vary by core count — run it on your machine.
