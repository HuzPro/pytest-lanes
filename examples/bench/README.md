# Bench example: a representative suite for comparing execution modes

The demo and containers examples show *mechanics*; this one is shaped for
*measurement*. It approximates how real suites actually behave, and every
cost in it is a documented real-world effect, not a synthetic handicap:

- **Tests burn real CPU** (calibrated pbkdf2 hashing; 1 unit ~ 1s of
  single-core work on the reference machine). Oversubscribed workers
  therefore contend for physical cores instead of parking for free the
  way sleeping tests do.
- **Each heavy lane pays a per-process environment spin-up** (a
  session-scoped autouse fixture burning CPU, standing in for a container
  or daemon boot). A lane child pays it once; each lane shard pays it
  again; every xdist worker that touches the directory pays its own copy.
- **Each test module pays an import cost** (module-level burn standing in
  for a real framework + app import graph). Every xdist worker collects
  the whole suite, so every worker pays the full import bill; lane
  children import only their own lane's files.

The shape (~114 units linear, lopsided file times):

| Lane | Files | Test units | Spin-up | Serial |
|---|---:|---:|---:|---:|
| `db_tests` | 6 | 56u (lopsided: 18u..4u per file) | 6u | 62u |
| `api_tests` | 3 | 19u | 3u | 22u |
| `unit_tests` | 8 | 30u (many small files) | none | 30u |

Tests are fully concurrency-safe by construction so every mode completes;
this example isolates scheduling economics, not safety (see
`examples/containers` for what shared state does to per-test
distribution).

## Run it

```bash
cd examples/bench
python bench.py            # 5 modes x (1 warm-up + 3 timed rounds)
python bench.py --runs 1   # quicker look
```

Modes: `serial`, `xdist-load` (`-n auto`), `xdist-loadfile`, `lanes`
(plain three-lane config), and `lanes-opt`: `divisible = files` on the
db lane (shard planning from recorded durations) plus
`lane_numprocesses = 4` on the unit lane (in-lane xdist). The warm-up
doubles as the measurement pass: it records per-file durations, which is
what lets the optimized mode's shard planner fire in the timed rounds.
First-ever runs never shard: no data, no split.

## Measured results

Measured on a 6-core CPU, medians of 3 rounds:

| Mode | Median | vs serial |
|---|---:|---:|
| serial | 126.9s | 1.0x |
| xdist `-n auto` | 57.6s | 2.20x |
| xdist `-n auto --dist loadfile` | 61.8s | 2.05x |
| lanes (plain) | 76.9s | 1.65x |
| **lanes-opt** | **51.1s** | **2.48x** |

Read it honestly:

- **lanes-opt beats the best xdist mode by 1.13x.** The costs that decide
  it are the per-worker import/collection bill and the duplicated
  environment spin-ups, both of which scale with worker count under xdist
  and with lane/shard count under lanes.
- **Plain lanes loses to xdist here** (76.9s vs 57.6s): its wall time is
  bounded by the whole 62u db lane. That is exactly the gap the optimized
  config closes: sharding attacks `min(T/2, D1 - D2)` from the T side,
  in-lane xdist from the D2 side.
- Remove the import and spin-up costs and xdist wins this suite outright
  (a sleep-based variant of this example measures xdist 24.9s vs
  lanes-opt 39.1s). Which model matches your suite is an empirical
  question: heavy import graphs and expensive per-process fixtures are
  the signal that lanes will pay.
