# pytest-lanes

[![tests](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml/badge.svg)](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml)

Lane-based parallel test orchestration for pytest suites whose cost is
dominated by heavy infrastructure: database containers, service singletons,
port-bound daemons, packaging builds.

A **lane** is a group of tests that share a marker and an execution
environment. Instead of distributing individual tests across workers the way
`pytest-xdist` does, pytest-lanes runs **one pytest subprocess per lane, in
parallel**. Each lane starts its environment once, runs its own tests in
order inside one clean process, and overlaps only with *other* lanes — the
only concurrency in the run is the concurrency you declared.

```
$ pytest .

Lane Test Summary
> postgres     : PASS (31.82s)
> timescale    : PASS (16.57s)
> acceptance   : PASS (1.07s)
> http_adapter : PASS (5.56s)
> other        : PASS (30.99s)
Parallelism ratio: 2.70x
Sum time without parallelization: 86.00s
Total time taken: 31.83s
```

## Why not pytest-xdist?

`pytest-xdist` distributes individual tests across a pool of identical
workers. That is the right model when your tests are homogeneous,
independent, and CPU-bound. It has three structural costs when your suite's
cost lives in *environments*:

- **Per-worker infrastructure.** Session/singleton fixtures live per
  process, so every worker that touches a Postgres-backed test starts its
  own container. The most expensive part of the suite gets multiplied, not
  divided.
- **Concurrency-safety becomes a per-test obligation.** Any test touching a
  process-global resource — a fixed port, a config file, OS registry state,
  a hardware device — can be scheduled alongside any other test. Either you
  audit and retrofit every such test (dynamic ports, unique paths, locks) or
  you get scheduling-dependent failures. Lanes make the safe orderings
  structural: tests only ever overlap with tests from other lanes.
- **Every worker collects everything.** Each xdist worker imports and
  collects the full suite before running anything (~8s per process on the
  suite below); lane subprocesses collect only their own paths.

Lane granularity is parallelism drawn along the infrastructure boundaries
you already have, expressed as config — and nothing inside a lane ever needs
to be made concurrency-proof.

### Measured results

Measured 2026-07 on the ~2,430-test production suite this plugin was
extracted from (five lanes: two Docker-container database lanes, an
acceptance lane, an HTTP adapter lane, and a unit fallback lane). Three
timed rounds per mode, interleaved, after one untimed warm-up per mode;
serial baseline measured once. Windows 11, AMD Ryzen 5 7600 (6C/12T),
16 GB RAM, NVMe SSD, Docker Desktop.

| Mode | Median (s) | Mean (s) | Min (s) | Max (s) | Stdev | Failures |
|---|---:|---:|---:|---:|---:|---:|
| **pytest-lanes** (`pytest .`) | **32.3** | 32.7 | 32.3 | 33.4 | 0.7 | 0 |
| xdist `-n auto --dist loadfile` | 37.3 | 38.5 | 36.1 | 42.2 | 3.2 | 0 |
| xdist `-n auto --dist loadscope` | 41.0 | 41.2 | 40.2 | 42.5 | 1.2 | 0 |
| xdist `-n auto` (default) | 41.9 | 42.3 | 41.9 | 43.2 | 0.7 | 0 |
| xdist `--dist loadgroup` + per-lane group marks | 54.1 | 54.9 | 53.3 | 57.4 | 2.2 | 2–16 |
| serial pytest (single process) | 68 | — | — | — | — | 0 |

Read it honestly:

- **Lanes: ~2.1x over serial and 1.15x–1.3x over pytest-xdist**, depending
  on how well you tune xdist's `--dist` mode. Every lanes run beat every
  xdist run (lanes max 33.4s < loadfile min 36.1s), with the lowest
  variance of any mode and no worker-count tuning.
- **The "make xdist do lanes" configuration is the interesting row.**
  Auto-applying an `xdist_group` mark per lane (the closest xdist
  equivalent of this plugin) was the *slowest* parallel mode — atomic
  groups serialize on single workers while the rest of the pool idles and
  every worker still pays full collection — and the only one that failed,
  with 2–16 scheduling-dependent database-schema failures per run. Group
  scheduling is per-*test*, so two tests from the same file can land in
  different groups on different workers; lane subprocesses are per-*path*
  and preserve the suite's natural ordering.
- **The gap depends on how concurrency-safe your suite already is.** An
  earlier (2026-05) snapshot of this same suite used fixed ZeroMQ ports in
  its e2e tests: xdist then posted 31 collision failures and lost by 2.2x
  (medians 59s vs 129s vs 155s serial, n=10). Two months of incremental
  work made those tests concurrency-safe (dynamic ports), and xdist's gap
  closed to the table above. That is the trade in one sentence: **you can
  buy xdist's speed by auditing and retrofitting every test that touches
  shared state — lanes give you parallel speed on the suite you have
  today, and stay correct when the next port-binding test lands.**

### Where the speedup comes from

Decomposed, using the run above:

1. **Environment-level concurrency** — the five lanes sum to 86s of
   subprocess time but wall-clock is 32s (2.70x overlap). This is the bulk
   of the win over serial pytest, and any parallel scheme gets some of it.
2. **Infrastructure paid once per environment, not once per worker** — the
   lane model starts one Postgres and one Timescale container per run;
   worker pools start one per worker that touches them.
3. **Scoped collection** — a full collection pass costs ~8s of the ~32s
   budget on this suite. Every xdist worker performs it; each lane
   subprocess collects only its own paths (0.8s of pytest time for the
   317-test HTTP lane).
4. **Ordering preserved inside a lane** — not a speedup, a correctness
   property the speed depends on: no failures means no reruns. See the
   `loadgroup` row above for what happens when the ordering is almost —
   but not exactly — preserved.

The honest caveats: maximum parallelism equals your lane count, a single
slow lane bounds the wall-clock (the 32s postgres lane above *is* the wall
time), and on a suite that is already fully concurrency-safe and
well-balanced, a tuned xdist lands within ~15% of lanes. The advantage
concentrates where suites actually live: partially concurrency-safe, with
a few expensive singletons. To see the mechanics on a small scale, run
[`examples/containers`](examples/containers) — real Postgres testcontainers,
lanes vs serial vs xdist, on your own machine.

## Installation

```bash
pip install pytest-lanes        # plain-text progress output
pip install pytest-lanes[rich]  # live progress table via rich
```

## Quickstart

### No config file

The fastest way in needs no INI section at all. `--lanes-auto` turns the
directory layout most projects already have into the partition — one lane
per immediate subdirectory of the rootdir that holds tests:

```bash
pytest . --lanes-auto
```

Or name lanes inline with `--lane-def name=path[,path...]` (repeatable),
handy for tox commands and one-off runs. Ad-hoc lanes are a partition and
fan-out instruction only — markers stay an INI feature:

```bash
pytest . --lane-def db=tests/integration --lane-def api=tests/api,tests/contracts
```

Either way, check the partition before trusting it: `--lanes-explain`
prints which lane claims each test and exits without running anything.

### Declaring lanes in INI

For durable, marker-aware lanes, declare them in `pytest.ini` (or
`tox.ini` / `setup.cfg`) next to your pytest markers:

```ini
[pytest]
markers =
    postgres_integration: postgres-backed integration tests
    unit: fast unit tests

[pytest-lanes]
lanes = postgres other
subprocess_order_standard = postgres other

[pytest-lanes:postgres]
marker = postgres_integration
classifier_path_prefixes = tests/integration/
subprocess_paths = tests/integration

[pytest-lanes:other]
marker = unit
classifier_fallback = true
subprocess_ignore_other_lanes = true
```

Then:

```bash
pytest .                          # fan out: one subprocess per lane, in parallel
pytest . --lanes-auto             # zero-config: one lane per test subdirectory
pytest . --lane-def db=tests/db    # define a lane inline, no config file
pytest . --lanes-full             # standard lanes + every optional lane
pytest . --lanes-max-workers=2    # cap concurrent lanes (default: CPU count)
pytest . --lanes-explain          # show which lane claims each test, run nothing
pytest --lane=postgres            # one lane, in-process, no fanout
pytest --lane=postgres,timescale  # multiple lanes, in-process
pytest -m unit                    # marker-only run; orchestration steps aside
pytest tests/test_foo.py          # path-targeted run; orchestration steps aside
pytest . -q --tb=long             # unrecognized flags pass through to every lane
```

If no `[pytest-lanes]` section exists, the plugin is dormant and pytest
behaves as if it were not installed — safe to keep in a shared environment.

Two runnable examples: [`examples/demo`](examples/demo) (no Docker, 30
seconds) and [`examples/containers`](examples/containers) (real Postgres
testcontainers, with a bench script comparing lanes vs serial vs xdist).

## Configuration reference

Lanes are declared under `[pytest-lanes]` and `[pytest-lanes:<name>]`
sections. Adding a lane is a config edit, not a Python edit.

The `[pytest-lanes]` index section:

| Field | Meaning |
|---|---|
| `lanes` (required) | All lane names in classification priority order — first matching rule wins. |
| `subprocess_order_standard` | Lane names that produce a subprocess in `pytest .` (default) mode, in launch order. |
| `subprocess_order_full` | Lane names that produce a subprocess in `pytest . --lanes-full` mode. Lanes here but not in `subprocess_order_standard` are "optional" (e.g. a slow build-verification lane). |
| `max_workers` | Maximum lanes running concurrently; default: CPU count. Overridden by `--lanes-max-workers`. |

Every `[pytest-lanes:<name>]` section accepts:

| Field | Meaning |
|---|---|
| `marker` (required) | Pytest marker applied to every test claimed by this lane. Must be declared in `[pytest].markers` in the same file. |
| `classifier_paths` | Exact relative paths this lane claims (whitespace-separated). |
| `classifier_path_prefixes` | Path prefixes this lane claims (e.g. `tests/integration/`). |
| `classifier_path_suffix` | A single filename suffix this lane claims (e.g. `_performance.py`). |
| `classifier_class_base_names` | Test-class base names. Classes whose MRO includes any of these are claimed regardless of file path — used to promote container-backed tests into their container lane wherever they live. |
| `classifier_fallback` | If `true`, this lane claims every item not claimed by an earlier rule. Exactly one lane should set this. |
| `subprocess_paths` | Paths passed as positional argv to the lane's pytest subprocess. |
| `subprocess_nodeids` | Specific test node IDs passed to the subprocess. |
| `subprocess_ignore` | Paths emitted as `--ignore=<path>` to the subprocess. |
| `subprocess_ignore_other_lanes` | If `true`, every other lane's paths are added to this lane's `--ignore=` list. The fallback lane uses this to "run everything not in another lane." |
| `subprocess_env_set` | Whitespace-separated `KEY=VALUE` entries injected into the subprocess env *and* applied per-test in single-process mode. |

### Adding a new lane

1. Declare a marker in `[pytest].markers`.
2. Add the lane name to `[pytest-lanes].lanes` (priority order matters).
3. Write one `[pytest-lanes:<name>]` section with at minimum `marker` and one classifier.
4. (Optional) Add the lane to `subprocess_order_standard` and/or `subprocess_order_full` if it should get its own subprocess.

## How it works

```
pytest .
  ├── pytest_cmdline_main (plugin hook)
  │     ├── orchestration_mode(config) -> "standard" | "full" | None
  │     ├── (if None: custom -k/-m/--lane/path selection, or we are a child)
  │     │     return None; pytest runs as usual
  │     ├── build_lane_commands(mode, passthrough_args, lane_config)
  │     │     -> N argv lists, one per subprocess lane
  │     └── run_lane_commands(commands, max_workers)
  │           ├── launch up to max_workers `python -m pytest <argv>` subprocesses;
  │           │     remaining lanes queue in declared order, start as slots free
  │           ├── set PYTEST_LANES_CHILD=1 so children skip re-orchestration
  │           ├── reader threads stream child stdout into a shared queue
  │           ├── LaneProgressReporter parses progress, counts, failures
  │           ├── live display renders (rich table, or plain text fallback)
  │           └── return max(exit codes)
  └── (for in-process runs) pytest_collection_modifyitems
        ├── classify each item -> LaneSpec (class-base-name > path rules > fallback)
        ├── apply the lane's marker
        └── if --lane=X was passed, skip items whose lane is not selected
```

Child processes detect the parent via `PYTEST_LANES_CHILD=1` and run as plain
pytest. That is the whole trick: each lane gets a clean interpreter, its own
fixtures, its own containers, its own ports — parallelism without any shared
mutable state. Setting `PYTEST_LANES_CHILD=1` in your own shell disables the
plugin entirely (useful for benchmarking the serial baseline).

Set `PYTEST_LANES_SHOW_OUTPUT=1` to stream every lane's raw output live in
addition to the progress table. A failing lane's full output is always
printed after the run, and each failed row in the Lane Test Summary is
followed by a `reproduce: pytest --lane=<name>` line — the exact command
to re-run that lane in isolation for debugging.

To see the partition before committing to a run, `--lanes-explain`
prints one line per collected test — the lane that claims it and the
classifier rule that matched — then exits without running anything.
Classification and explanation share one code path, so the listing
cannot drift from what a real run would do:

```
$ pytest . --lanes-explain

Lane classification
io_tests/test_simulated_container.py::test_simulated_container_query_one -> slow_io (classifier_path_prefixes: io_tests/)
io_tests/test_simulated_container.py::test_simulated_container_query_two -> slow_io (classifier_path_prefixes: io_tests/)
unit_tests/test_fast_units.py::test_unit_alpha -> other (classifier_fallback)
unit_tests/test_fast_units.py::test_unit_beta -> other (classifier_fallback)
4 tests in 2 lanes
```

It inspects whatever would be collected, so it composes with the usual
`-k`/`-m`/path selection. (Needs a `[pytest-lanes]` config — with none,
it reports a usage error rather than guessing.)

## When to use it (and when not to)

**Good fit** — your suite has clusters of tests bound to expensive, stateful
environments: testcontainers (Postgres, TimescaleDB, Kafka, ...), daemons on
fixed ports, OS-level state, packaging/build verification. Especially when
those fixtures are process-wide singletons that were never designed for
multi-worker access.

**Poor fit** — thousands of homogeneous, independent, CPU-bound unit tests
with no shared infrastructure. That is exactly what `pytest-xdist` is for.
The two are complementary: lanes for environment isolation, xdist for
test-level spreading within an environment.

### Prior art

| Tool | Granularity | Difference |
|---|---|---|
| `pytest-xdist` | per-test | Fastest option for homogeneous CPU-bound suites. Per-process fixtures duplicate per worker, every worker collects the full suite, and process-global state must be made concurrency-safe test by test — see [Measured results](#measured-results) for how its `--dist` modes compare. |
| `pytest-split` / `pytest-shard` | per-CI-node | Splits a suite across machines by timing for CI sharding; no local parallelism, no environment alignment. |
| `tox -p` / `nox` | per-environment | Parallel *virtualenvs* — each env reinstalls dependencies, output is siloed per env, and selection lives outside pytest. pytest-lanes runs in one env, one command, one aggregated summary. |
| shell scripts / `make -j` | per-command | No classification, no marker application, no passthrough args, no unified failure report. |

## Hardware requirements

The speedup is bought with CPU cores. Wall-clock gain is bounded by
`min(concurrent lanes, physical cores)`: a lane is a full pytest process
that can keep a core busy, so the working guideline is roughly one core
per concurrent lane.

Lanes beyond `max_workers` (default: CPU count) queue and launch as slots
free, so on a 1–2 core machine a multi-lane suite degrades toward serial
execution plus subprocess overhead — the plugin schedules the parallelism
you declared, but it cannot create parallelism the hardware does not have.

Memory scales the same way: each concurrent lane costs a full Python
interpreter plus that lane's own infrastructure — one Postgres container
per database lane running at the same time, and so on.

For CI, size the runner to the concurrency you want. GitHub Actions'
`ubuntu-latest` gives 4 vCPUs, so more than ~4 concurrent lanes will not
pay off there. And `os.cpu_count()` (the `max_workers` default) reports
*logical* cores; the honest guideline is physical cores, so on
SMT/hyper-threaded machines consider setting `max_workers` lower.

## Limitations

- No in-lane parallelism yet: a single slow lane bounds the wall-clock.
- Max parallelism is `min(subprocess lane count, max_workers)`; lanes
  beyond that queue and wait for a free slot.
- Queued lanes launch in declared order (`subprocess_order_standard`), so
  list the slowest lanes first until duration-aware ordering exists.
- Persistent config is INI-only (`pytest.ini`, `tox.ini`, `setup.cfg`); the
  `--lane-def` and `--lanes-auto` flags define lanes with no file, but
  `pyproject.toml` is not supported yet.
- INI lane config must live in the same file that declares
  `[pytest].markers`.
- Lane-to-marker mapping is one marker per lane; multiple lanes may share a
  marker.
- The orchestrator aggregates child exit codes and output; plugins that need
  a single test session (e.g. combined coverage) require per-lane data
  combination (e.g. `coverage combine`).

## Roadmap

Details and sequencing in [ROADMAP.md](ROADMAP.md). v0.2 shipped the
bounded worker pool, the trust and debugging tools (`--lanes-explain`, a
live ETA, and reproduce hints), and zero-config lanes (`--lane-def` and
`--lanes-auto`, no config file required); the headlines from here, in
order:

- **Duration cache** — recorded per-lane wall times feeding longest-first
  scheduling and real ETAs, replacing today's declared-order queueing.
- **`--lanes-suggest`** — inspects a suite statically and prints a
  proposed `[pytest-lanes]` config: the differentiator no other tool has.

## Development

```bash
git clone https://github.com/HuzPro/pytest-lanes
cd pytest-lanes
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e .[test]
pytest
```

The suite includes end-to-end tests that generate a miniature lane project
in a temp directory and run a real orchestrated `pytest` against it.

## License

[MIT](LICENSE)
