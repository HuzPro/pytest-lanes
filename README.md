# pytest-lanes

[![tests](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml/badge.svg)](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml)

Lane-based parallel test orchestration for pytest suites whose cost is
dominated by heavy infrastructure: database containers, service singletons,
port-bound daemons, packaging builds.

A **lane** is a group of tests that share a marker and an execution
environment. Instead of distributing individual tests across workers the way
`pytest-xdist` does, pytest-lanes runs **one pytest subprocess per lane, in
parallel**. Each lane pays its infrastructure cost exactly once, in a fully
isolated process, and nothing is ever shared across workers mid-test.

```
$ pytest .

Lane Test Summary
> postgres     : PASS (21.32s)
> timescale    : PASS (8.04s)
> acceptance   : PASS (12.51s)
> http_adapter : PASS (4.22s)
> other        : PASS (19.10s)
Parallelism ratio: 2.62x
Sum time without parallelization: 65.19s
Total time taken: 24.86s
```

## Why not pytest-xdist?

`pytest-xdist` parallelizes at *test* granularity. That is the right
granularity when your suite is a large pile of homogeneous, CPU-bound unit
tests. It is the wrong granularity when your suite's cost lives in
*environments*:

- **Container duplication.** Every xdist worker that touches a
  Postgres-backed test spins up its own container (or fights over a shared
  one). The most expensive part of the suite gets multiplied, not divided.
- **Singleton collisions.** Session-scoped container fixtures, fixed port
  allocations (ZeroMQ, HTTP daemons), registry/config state — xdist workers
  stomp on each other because the fixtures were designed for one process.
- **Unshardable tests.** A single end-to-end packaging build can't be split
  across workers; it just serializes everything behind it.

Lane granularity fixes all three at once: parallelism follows the
infrastructure boundaries you already have, expressed as config.

### Measured results

Measured on the production suite this plugin was extracted from (six lanes:
two Docker-container database lanes, an acceptance lane, a PyInstaller
build-verification lane, an HTTP adapter lane, and a unit fallback lane).
Ten timed runs per mode, interleaved rounds, one untimed warm-up per mode,
same machine and session (Windows 11, AMD Ryzen 5 7600, 16 GB RAM, NVMe SSD):

| Mode | Mean (s) | Median (s) | Min (s) | Max (s) | Stdev (s) |
|---|---:|---:|---:|---:|---:|
| **pytest-lanes** (`pytest . --lanes-full`) | **58.01** | 58.92 | 50.52 | 64.05 | 3.98 |
| **pytest-xdist** (`pytest . -n auto`) | 127.11 | 129.22 | 92.43 | 170.10 | 22.78 |
| **vanilla** (`pytest .`) | 154.13 | 154.91 | 125.70 | 193.08 | 20.07 |

**~2.7x faster than vanilla pytest and ~2.2x faster than pytest-xdist**, with
distributions that do not overlap: the *worst* lane-orchestrated run (64s)
was still faster than the *best* xdist run (92s). The gap is structural, not
statistical noise.

xdist only bought ~1.2x over vanilla on this suite because per-worker
container spin-up ate the parallelism win — and its test distribution broke
singleton container fixtures and port allocations, producing 31 real
failures on top. Lane-level parallelism is the right granularity for suites
shaped like this; test-level parallelism is the right granularity inside a
single homogeneous lane (see [Roadmap](#roadmap)).

## Installation

```bash
pip install pytest-lanes        # plain-text progress output
pip install pytest-lanes[rich]  # live progress table via rich
```

## Quickstart

Declare lanes in `pytest.ini` (or `tox.ini` / `setup.cfg`) next to your
pytest markers:

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
pytest . --lanes-full             # standard lanes + every optional lane
pytest --lane=postgres            # one lane, in-process, no fanout
pytest --lane=postgres,timescale  # multiple lanes, in-process
pytest -m unit                    # marker-only run; orchestration steps aside
pytest tests/test_foo.py          # path-targeted run; orchestration steps aside
pytest . -q --tb=long             # unrecognized flags pass through to every lane
```

If no `[pytest-lanes]` section exists, the plugin is dormant and pytest
behaves as if it were not installed — safe to keep in a shared environment.

A runnable two-lane example lives in [`examples/demo`](examples/demo).

## Configuration reference

Lanes are declared under `[pytest-lanes]` and `[pytest-lanes:<name>]`
sections. Adding a lane is a config edit, not a Python edit.

The `[pytest-lanes]` index section:

| Field | Meaning |
|---|---|
| `lanes` (required) | All lane names in classification priority order — first matching rule wins. |
| `subprocess_order_standard` | Lane names that produce a subprocess in `pytest .` (default) mode, in launch order. |
| `subprocess_order_full` | Lane names that produce a subprocess in `pytest . --lanes-full` mode. Lanes here but not in `subprocess_order_standard` are "optional" (e.g. a slow build-verification lane). |

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
  │     └── run_lane_commands(commands)
  │           ├── spawn N `python -m pytest <argv>` subprocesses
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
printed after the run.

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
| `pytest-xdist` | per-test | Workers share nothing *and* everything: fixtures duplicate per worker, singletons collide. No environment awareness. |
| `pytest-split` / `pytest-shard` | per-CI-node | Splits a suite across machines by timing for CI sharding; no local parallelism, no environment alignment. |
| `tox -p` / `nox` | per-environment | Parallel *virtualenvs* — each env reinstalls dependencies, output is siloed per env, and selection lives outside pytest. pytest-lanes runs in one env, one command, one aggregated summary. |
| shell scripts / `make -j` | per-command | No classification, no marker application, no passthrough args, no unified failure report. |

## Limitations

- No in-lane parallelism yet: a single slow lane bounds the wall-clock.
- Max parallelism equals the number of subprocess lanes.
- Configuration is INI-only (`pytest.ini`, `tox.ini`, `setup.cfg`);
  `pyproject.toml` is not supported yet.
- Lane config must live in the same file that declares `[pytest].markers`.
- Lane-to-marker mapping is one marker per lane; multiple lanes may share a
  marker.
- The orchestrator aggregates child exit codes and output; plugins that need
  a single test session (e.g. combined coverage) require per-lane data
  combination (e.g. `coverage combine`).

## Roadmap

- Layer `pytest-xdist` *inside* a lane (`lane_numprocesses`) so homogeneous
  lanes get test-level spreading too.
- `pyproject.toml` (`[tool.pytest-lanes]`) configuration.
- Per-lane OS gating (`requires_os`) for platform-specific lanes.

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
