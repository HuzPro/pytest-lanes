# pytest-lanes

[![tests](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml/badge.svg)](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-lanes.svg)](https://pypi.org/project/pytest-lanes/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-lanes.svg)](https://pypi.org/project/pytest-lanes/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/HuzPro/pytest-lanes/blob/main/LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Parallel pytest for suites that cannot be made concurrency-safe.**

One pytest subprocess per declared **lane**, so your tests only ever overlap
across environment boundaries *you* chose. The name is the mental model:
lanes run alongside each other and never merge.

<img src="https://raw.githubusercontent.com/HuzPro/pytest-lanes/main/docs/lane-run.svg" alt="pytest-lanes running four lanes in parallel: db~1of2, db~2of2, unit and api, finishing in 49.10s against 142.51s of serial subprocess time — a 2.90x parallelism ratio" width="100%">

A **lane** is a group of tests that share a marker and an execution
environment. Each lane starts its environment once, runs its own tests in
declaration order inside one clean process, and overlaps only with *other*
lanes — so nothing inside a lane ever needs to be made concurrency-proof.
(The run above is [`examples/bench`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/bench);
`db~1of2` and `db~2of2` are one declared lane that the planner
[split in two](#sharding-splitting-a-slow-lane) because the measured
durations said it would pay.)

### Is this for you?

| Your situation | What to reach for |
|---|---|
| Homogeneous, independent, CPU-bound unit tests | **`pytest-xdist`.** It will beat this, and it is one dependency you probably already have. |
| Grouping needs fit `--dist loadfile` / `loadscope` / `loadgroup` | **`pytest-xdist`.** Try it first — genuinely. |
| Tests share fixed ports, one DB schema, OS state, a licensed simulator — and retrofitting them all is not happening | **pytest-lanes.** Safe orderings become structural instead of a per-test obligation. |
| You need setup/teardown per *group*, not per worker | **pytest-lanes.** A lane is the process, so its session fixtures wrap exactly its own tests. |
| Expensive setup can't be duplicated or serialized cheaply (a 4 GB model, an in-process index, one container) | **pytest-lanes.** |
| Most of your suite's time sits in one huge test file | **`pytest-xdist`.** A file is a lane's atomic unit, so that file is your floor. |

The honest version of this table, with the reasoning and the xdist
limitations that are structural rather than incidental, is in
[Should you use this?](#should-you-use-this).

## Quickstart

```bash
pip install pytest-lanes[rich]     # rich gives the live progress table above
```

Then pick a partition. You do not have to write one by hand:

```bash
pytest --lanes-suggest    # propose a lane config from your layout, run nothing
pytest . --lanes-auto     # zero config: one lane per test subdirectory
pytest . --lanes-explain  # show which lane claims each test, run nothing
pytest .                  # fan out: one subprocess per lane, in parallel
```

Paste the suggestion into `pytest.ini` or `pyproject.toml` when you are happy
with it, and `pytest .` is your parallel command from then on. Run the suite
once with lanes and `--lanes-suggest` starts proposing a **duration-balanced**
partition from what it measured, instead of guessing from your directory
names.

Install without extras if you prefer plain-text progress output; `rich` is
optional. Nothing changes for anyone who runs `pytest -k foo`, `pytest -m unit`,
or `pytest path/to/test.py` — orchestration steps aside for targeted runs, and
with no lane config the plugin is completely dormant.

Two runnable examples:
[`examples/demo`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/demo)
(no Docker, 30 seconds) and
[`examples/containers`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/containers)
(real Postgres testcontainers, with a benchmark script).

## Contents

- [Should you use this?](#should-you-use-this) — and when not to
- [Measured results](#measured-results) — this suite, plus four public repos
- [Defining lanes](#defining-lanes) — zero-config, INI, `pyproject.toml`
- [Configuration reference](#configuration-reference) — every key
- [Command-line reference](#command-line-reference) — every flag
- [How it works](#how-it-works) — classification, fan-out, reporting
- [Coverage and JUnit in CI](#coverage-and-junit-reports-in-ci)
- [Hardware requirements](#hardware-requirements) — cores per lane, honestly
- [Sharding a slow lane](#sharding-splitting-a-slow-lane) and
  [in-lane xdist](#in-lane-xdist-lane_numprocesses)
- [Limitations](#limitations) · [FAQ](#faq) · [Roadmap](#roadmap)

## Should you use this?

**Use `pytest-xdist` if** your tests are homogeneous, independent and
CPU-bound; or if the grouping you need fits `--dist loadfile` /
`--dist loadscope` / `--dist loadgroup` with `@pytest.mark.xdist_group`.
That last mode covers a lot of ground — named groups that never run
concurrently with themselves — and it is one dependency you probably
already have. Try it first. Honestly.

**Consider pytest-lanes when one of these actually applies:**

- **Retrofitting your tests for concurrency-safety is not on the table.**
  Any test touching a process-global resource — a fixed port, a shared
  schema, a config file, OS registry state, a hardware device — can be
  scheduled alongside any other test under a worker pool. Either you audit
  and fix every one of them, or you accept scheduling-dependent failures.
  Lanes make the safe orderings structural instead: tests only ever overlap
  with tests from *other* lanes, and nothing inside a lane needs to be made
  concurrency-proof.
- **You need a fixture lifecycle per group, not per worker.** xdist's unit
  of isolation is the worker, and groups are assigned to workers
  round-robin, so several unrelated groups share one process and its
  session state. A lane *is* the process: its session fixtures set up and
  tear down around exactly its own tests.
- **The expensive setup cannot be shared or duplicated cheaply.** The
  documented xdist recipe for a single shared fixture
  ([`tmp_path_factory` + `FileLock`](https://pytest-xdist.readthedocs.io/en/stable/how-to.html))
  can only hand a small serialized value between workers — it cannot share a
  4 GB model, an in-process index, or a daemon holding a fixed port. Note
  that Python's testcontainers has no container-reuse support at all
  ([open since 2020](https://github.com/testcontainers/testcontainers-python/issues/109)).
- **You want `-s` and `--pdb` to keep working.** xdist's own docs list both
  as unsupported, because worker stdout cannot be transferred. A lane is a
  plain pytest subprocess, so `-s` streams live; and `pytest --lane=<name>`
  runs one lane in-process, where `--pdb` behaves normally.
- **Every worker collects everything.** Each xdist worker imports and
  collects the full suite before running anything (~8s per process on the
  suite below); lane subprocesses collect only their own paths.

**A cost worth stating plainly:** the *boot* time of containers is usually
not the problem people assume it is. Eight workers starting eight Postgres
containers start them *concurrently* — roughly one container's wall-clock
latency, not eight. Per-worker duplication genuinely hurts when setup is
**serialized CPU work** (migrations, fixture seeding, loading a model or
index), when it **exhausts a resource** (memory, connection limits, disk),
or when the resource is **irreducibly singleton** (one licensed simulator,
one fixed port, one piece of hardware). If your containers just boot fast
and your tests are independent, xdist will serve you fine.

### Measured results

Speed is not the argument for this plugin, but it should at least not cost
you any — so here is the data, including the cases where it loses.

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

- **Lanes: ~2.1x over serial, and on this suite a modest 1.15x–1.3x over
  pytest-xdist** depending on how well xdist's `--dist` mode is tuned. Treat
  that second number as "no worse", not as a selling point: it is one suite,
  on one machine, and the [public-suite results](#validated-on-public-suites)
  below include a case where xdist wins outright. What is consistent here is
  the low variance and the absence of worker-count tuning.
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
   worker pools start one per worker that touches them. On this suite the
   cost of that duplication is memory and connection pressure rather than
   boot latency (containers boot concurrently), so do not expect this term
   to dominate on every suite.
3. **Scoped collection** — a full collection pass costs ~8s of the ~32s
   budget on this suite. Every xdist worker performs it; each lane
   subprocess collects only its own paths (0.8s of pytest time for the
   317-test HTTP lane).
4. **Ordering preserved inside a lane** — not a speedup, a correctness
   property the speed depends on: no failures means no reruns. See the
   `loadgroup` row above for what happens when the ordering is almost —
   but not exactly — preserved.

The honest caveats: maximum parallelism equals your lane count; a single
slow lane bounds the wall-clock (the 32s postgres lane above *is* the wall
time); the atomic unit is a **file**, so a suite whose weight sits in one
huge test file has a floor lanes cannot get under (xdist's test-level
distribution can, if your suite tolerates it); and on a suite that is
already fully concurrency-safe and well-balanced, a tuned xdist lands
within ~15% — sometimes ahead. The advantage concentrates where suites
actually live: partially concurrency-safe, with a few expensive
singletons. To see the mechanics on a small scale, run
[`examples/containers`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/containers) — real Postgres testcontainers,
lanes vs serial vs xdist, on your own machine.

### Validated on public suites

The same protocol (medians of 3 timed rounds after warm-up, identical
test populations and per-repo environment exclusions across every mode,
Windows 11, 6C/12T) run against four well-known pytest suites, chosen to
cover the spectrum from container-heavy to pure-CPU. "best xdist" is the
best-performing safe `--dist` mode for that suite. "lanes-balanced" is
the config `--lanes-suggest` generates from recorded durations, with
shared-service tests co-located by hand as its header instructs.

| Suite | serial | best xdist | lanes | lanes tuned | Verdict |
|---|---:|---:|---:|---:|---|
| testcontainers-python (7 container modules) | 237.1 | 131.0 | **121.9** | — | **lanes wins.** Container-per-module is the natural lane shape; their own Makefile runs modules serially, so lanes is a drop-in 1.9x. |
| litestar (`tests/unit`, docker-coupled tests excluded everywhere) | 59.1 | 33.4 | 54.0 | **20.2** (balanced) | **lanes wins, but only the measured config.** The naive 5-lane split leaves one dominant lane (54.0); the duration-balanced partition beats their tuned loadgroup setup 1.65x. |
| flask-admin (postgres/mongo/azurite services) | 44.3 | 29.8 (loadfile) / 14.4 (load) | 30.3 | 23.4 (sharded) | **split.** At file granularity lanes wins (23.4 vs 29.8). One 19.2s test file is 43% of the suite — test-granular `--dist load` is the only way past that floor, if your suite tolerates it (theirs has no concurrency-safety marks; it happened to pass here). |
| pydantic (pure CPU control) | 17.9 | 12.7 | 12.2 | 11.7 | **wash, by design.** Homogeneous CPU-bound units are xdist's home turf; lanes matching it is the interesting part (xdist needed `PYTHONHASHSEED` pinned to collect deterministically at all; lanes ran the suite unmodified). |

What the four quadrants say in one paragraph: lanes wins where the suite's
cost lives in *environments* (containers per module, service singletons) or
where measured rebalancing can fix a lopsided partition — and the win comes
without retrofitting a single test. xdist wins when weight concentrates in
single files (lanes' granularity floor is the file) *and* test-granular
distribution is safe for the suite. On pure CPU suites the two are within
noise of each other. Full tables, exclusion lists, and methodology notes
per suite are in the repo history.

## Defining lanes

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

Don't want to write the INI at all? `pytest --lanes-suggest` reads your
directory layout and `conftest.py` files statically — fixture scopes and
infrastructure imports, running no test code — and prints a commented
`[pytest-lanes]` block to review and paste in, then exits without running
tests:

```bash
pytest --lanes-suggest
```

```ini
# pytest-lanes suggestion - generated by --lanes-suggest from static
# analysis (directory layout + conftest.py imports and fixture scopes).
# Review and adjust, then verify the partition with:
#     pytest . --lanes-explain

[pytest-lanes]
lanes = db_tests unit_tests other
subprocess_order_standard = db_tests unit_tests

[pytest-lanes:db_tests]
# detected: session/module-scoped fixtures: daemon_port
marker = db_tests
classifier_path_prefixes = db_tests/
# ... one section per lane, above a [pytest] markers block (elided)
```

It is a starting point from static structure, not an oracle: verify with
`--lanes-explain` before trusting it, and with fewer than two test-bearing
subdirectories it says so instead of guessing.

Once recorded per-file durations exist (any lane-config run records
them), `--lanes-suggest` stops guessing from structure and prints a
**duration-balanced partition** instead: files pack longest-first into up
to `min(CPU count, 8)` lanes so the lanes finish at roughly the same
time, whole directories preferred, with projected seconds on every lane
and a `rest` catch-all so tests added after recording still run:

```ini
# pytest-lanes balanced suggestion - generated by --lanes-suggest from
# recorded per-file durations, not from static analysis.
# Measured: 77.0s across 197 files; the
# balance is only as current as that recording.

[pytest-lanes:serialization]
# projected: 9.8s
marker = serialization
divisible = files
classifier_path_prefixes = tests/unit/serialization/
subprocess_paths = tests/unit/serialization
# ... one section per lane, then a tolerant [pytest-lanes:rest] catch-all
```

The balance sees durations only, not coupling: files that talk to the
same shared external service (one container, one database, one compose
project) must be moved into the same lane by hand, or the lanes race each
other's setup and teardown.

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

If no lane configuration exists, the plugin is dormant and pytest behaves as
if it were not installed — safe to keep in a shared environment.

## Command-line reference

| Command | What it does |
|---|---|
| `pytest .` | Fan out: one subprocess per lane, in parallel. |
| `pytest . --lanes-auto` | Zero config — one lane per test subdirectory. |
| `pytest . --lane-def db=tests/db` | Define a lane inline, no config file. Repeatable. |
| `pytest --lanes-suggest` | Print a suggested lane config and exit. Duration-balanced once data exists. |
| `pytest . --lanes-explain` | Print which lane claims each test and exit. |
| `pytest . --lanes-full` | Standard lanes plus every optional lane. |
| `pytest . --lanes-max-workers=2` | Cap concurrent lanes (default: CPU count). |
| `pytest . --lanes-no-shard` | Disable shard planning for this run. |
| `pytest . --lanes-show-output` | Stream every lane's output live, not just failures. |
| `pytest --lane=postgres` | Run one lane in-process, no fan-out — where `--pdb` works. |
| `pytest --lane=postgres,timescale` | Several lanes in-process. |
| `pytest . -s` | Disables capture, so lane output streams live. |
| `pytest -m unit` / `pytest tests/test_foo.py` | Targeted run; orchestration steps aside. |
| `pytest . -q --tb=long --junitxml=r.xml` | Unrecognized flags pass through to every lane. |

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
| `shard_min_saving` | Minimum projected makespan improvement, in seconds, before a divisible lane is split into two shards; default 5. See [Sharding](#sharding-splitting-a-slow-lane). |

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
| `lane_numprocesses` | If `> 1`, run this lane's subprocess under pytest-xdist (`-n N --dist loadfile`). For homogeneous lanes whose environment is cheap to duplicate; requires pytest-xdist. Reintroduces per-worker environment duplication *inside* this lane. See [Sharding](#sharding-splitting-a-slow-lane). |
| `divisible` | Set to `files` to opt this lane into sharding — asserting its files are mutually independent and its environment tolerates a duplicate running alongside it. See [Sharding](#sharding-splitting-a-slow-lane). |
| `tolerate_no_tests` | If `true`, this lane collecting zero tests counts as success instead of failing the run. Meant for catch-all lanes that may legitimately come up empty. |

This schema is frozen for the whole 0.x series: keys will be added, never
renamed or removed.

### The same schema in `pyproject.toml`

Everything above can live in `pyproject.toml` instead, under
`[tool.pytest-lanes]` — same keys, same meanings, TOML types instead of
whitespace-delimited strings:

```toml
[tool.pytest.ini_options]
markers = ["postgres_integration: postgres-backed integration tests"]

[tool.pytest-lanes]
lanes = ["postgres", "other"]
subprocess_order_standard = ["postgres", "other"]
max_workers = 3

[tool.pytest-lanes.lane.postgres]
marker = "postgres_integration"
classifier_path_prefixes = ["tests/integration/"]
subprocess_paths = ["tests/integration"]
subprocess_env_set = { DATABASE_URL = "postgresql://localhost/test" }

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_fallback = true
subprocess_ignore_other_lanes = true
```

Markers are validated against `[tool.pytest.ini_options].markers` in the
same file. Discovery follows pytest's own config precedence — `pytest.ini`,
then `pyproject.toml`, then `tox.ini`, then `setup.cfg`; the first file
declaring lane configuration wins. Because TOML carries real types, the
pyproject loader is stricter than the INI one: a misspelled key, a string
where an array belongs, or a float where an integer belongs is a config
error naming the offending field, not something silently ignored.

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
  │           │     remaining lanes queue longest-first from recorded durations
  │           │     (declared order on the first run), start as slots free
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

Those recorded durations persist to
`.pytest_cache/v/pytest-lanes/lane_durations.json` between runs — each
lane's record now holds per-file test times plus measured `startup`
(collection end to first test, which captures container/fixture spin-up)
and `collect` — and deleting that file resets scheduling to declared
order.

Child processes detect the parent via `PYTEST_LANES_CHILD=1` and run as plain
pytest. That is the whole trick: each lane gets a clean interpreter, its own
fixtures, its own containers, its own ports — parallelism without any shared
mutable state. Setting `PYTEST_LANES_CHILD=1` in your own shell disables the
plugin entirely (useful for benchmarking the serial baseline).

`-s` (or `--capture=no`) works as it does in plain pytest: capture is off
in the lane children and their output streams live, prefixed per lane.
`--lanes-show-output` does the same without disabling capture, when you
want to watch lanes progress rather than see `print()` output; the
`PYTEST_LANES_SHOW_OUTPUT=1` environment variable is equivalent, for CI
jobs that cannot change the pytest command. A failing lane's full output is
always printed after the run, and each failed row in the Lane Test Summary
is followed by a `reproduce: pytest --lane=<name>` line — the exact command
to re-run that lane in isolation. That command runs **in-process**, which
is where `--pdb` works normally (a debugger cannot attach to a lane
subprocess, and xdist has the same limitation with no in-process escape
hatch).

### Coverage and JUnit reports in CI

`--junitxml` and `--cov` work as they do in a single-process run, because
each lane is staged to its own file and the parent aggregates afterwards:

```bash
pytest . --junitxml=report.xml --cov=src --cov-report=xml:coverage.xml
```

`report.xml` holds every lane's test cases, with correct totals on the root
element; `coverage.xml` and the `.coverage` data file are combined across
all lanes. Without this, each lane would write the same path — coverage's
SQLite data file corrupts outright, and a JUnit report silently keeps only
whichever lane finished last. If you have ever wired lanes up by hand with
several pytest invocations, this is the part that is easy to get wrong.

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
with no shared infrastructure. That is exactly what `pytest-xdist` is for,
and it will beat this. Also a poor fit when most of your suite's time sits
in one very large test file: a file is a lane's atomic unit, so that file
becomes your floor. The two tools are complementary — lanes for environment
isolation, xdist for test-level spreading within an environment — and the
built-in `lane_numprocesses` key does exactly that inside a single
homogeneous lane (see
[Sharding: splitting a slow lane](#sharding-splitting-a-slow-lane)).

### Prior art

Read this table as "what else to try first", not as a list of things this
plugin beats.

| Tool | Granularity | Difference |
|---|---|---|
| `pytest-xdist` | per-test | The default answer, and the fastest option for homogeneous CPU-bound suites. `--dist loadgroup` + `xdist_group` marks covers much of what lanes do for scheduling. What it cannot do: give each group its own process lifecycle (groups share workers round-robin), preserve grouping without per-test marks, or support `-s`/`--pdb` (its docs list both as unsupported). |
| `pytest-isolated` | per-marked-group subprocess | The closest design to this one — grouped subprocesses with per-group fixtures and ini config. It runs its groups **serially**, so it buys isolation but no parallelism. |
| `pytest-shared-session-scope` | per-fixture | Attacks the duplicated-session-fixture problem directly by sharing one fixture's value across xdist workers. Lighter than lanes if fixture duplication is your *only* problem and the value serializes. |
| `pytest-split` / `pytest-shard` | per-CI-node | Splits a suite across machines by timing; no local parallelism, no environment alignment. Composes with lanes: shard across nodes, lanes within a node. |
| `tox -p` / `nox` | per-environment | Parallel *virtualenvs* — genuinely overlapping subprocesses with aggregated exit codes today. Each env reinstalls dependencies, output is siloed per env, and selection lives outside pytest. |
| Pants / Bazel / Buck2 | per-target batch | Build systems that already do config-declared test batching in parallel, with resource slots to avoid port/DB collisions. Strictly more capable; vastly more adoption cost. If you are already on one, use it. |
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

## Sharding: splitting a slow lane

A single slow lane bounds the wall-clock. If that lane's files are
mutually independent and its environment can run duplicated, pytest-lanes
can split the lane into two shards that run as separate subprocesses — a
second copy of the environment bought for a shorter critical path.

Sharding is opt-in per lane, because the split is only safe under two
assertions you make by declaring it:

```ini
[pytest-lanes:postgres]
marker = postgres_integration
classifier_path_prefixes = tests/integration/
divisible = files
```

`divisible = files` asserts (1) the lane's files are mutually independent
— no ordering or cross-file shared state — and (2) the environment
tolerates a duplicate running alongside it. A lane bound to a fixed port
or a single-instance daemon must **not** opt in: a second shard starts a
second copy and the two collide. Splits are always at file granularity and
never reorder within a file, so the "only the concurrency you declared"
property holds — a shard is just a subset of the lane's files in their
normal order.

**The plan is static, computed before launch.** Sharding never fires on
the first run — no recorded data, no split. Once durations exist, the
planner replays the real scheduler — bounded worker pool, longest-first —
twice: once with every lane whole, once with a 2-way contiguous split of
the single longest divisible lane. It keeps the split only when the
projected makespan improves by at least `shard_min_saving` (default 5s),
counting each shard re-paying its measured startup + collect. One lane is
considered per run.

The cut is deterministic and sticky: same inputs, same plan. It persists
to `.pytest_cache/v/pytest-lanes/shard_plan.json` and is re-cut — loudly —
only when recorded durations drift past 20% imbalance. Shard 1 runs an
explicit file list; shard 2 runs the lane minus those files (an
ignore-list), so a file added since the plan was recorded always runs, and
shard 2 tolerates collecting nothing.

A sharded run prints a receipt and splits the lane's live row in two:

```
pytest-lanes: sharded postgres into 2: projected 17.1s + 16.4s, makespan gain 13.0s >= 5.0s

> postgres~1of2 : PASS (17.24s)
> postgres~2of2 : PASS (16.51s)
```

Shard measurements merge back into the parent lane's record, so scheduling
and future plans still see `postgres` as one lane. A failed shard prints
two reproduce lines — the whole lane, and the shard's exact files:

```
reproduce: pytest --lane=postgres
    or: pytest tests/integration/test_a.py tests/integration/test_b.py
```

`--lanes-no-shard` disables planning for a run; the `--lanes-explain`
footer lists the divisible lanes and the persisted plan.

**The honest ceiling.** Splitting the longest lane cannot help more than
the runner-up lets it. For a longest lane of duration `D1 = E + T` (fixed
environment cost `E` plus test time `T`) and a second-longest lane `D2`, a
single 2-way split saves at most

    min(T / 2, D1 - D2)

The `T/2` term is the best case of halving the test work; the `D1 - D2`
term is the wall the next-longest lane now sets. On a balanced suite
`D1 - D2` is small and sharding alone is nearly worthless — shrink the
second-longest lane first, then sharding the expensive lane pays.

### In-lane xdist (`lane_numprocesses`)

For a lane that is homogeneous and cheap to duplicate — many independent
files, a fast or shareable environment — `lane_numprocesses = N` runs that
lane's own subprocess under pytest-xdist (`-n N --dist loadfile`). It is
the built-in way to spread tests across workers *within a single
environment*: lanes give you environment isolation, this gives you
test-level parallelism inside one lane. It requires pytest-xdist installed
(a clear usage error otherwise). The honest trade is that inside that lane
xdist's costs come back — each worker duplicates the lane's per-worker
environment, and process-global state must be concurrency-safe across the
lane's own files — which is exactly the opt-in you make by setting the key.

The two features compose. `lane_numprocesses` on a cheap, fat lane is
often the cleanest way to shrink the second-longest lane, which is what
lifts the `D1 - D2` ceiling above and lets sharding the expensive lane
cash in its `T/2`.

## Limitations

- Wall-clock is bounded by the slowest shard/worker-set, not the slowest
  test. In-lane parallelism exists but is opt-in per lane:
  `lane_numprocesses` spreads a lane across xdist workers, and
  `divisible = files` lets the planner shard a slow lane. A lane that opts
  into neither runs whole and bounds the run if it is the longest.
- Max parallelism is `min(subprocess lane count, max_workers)`; lanes
  beyond that queue and wait for a free slot.
- Queued lanes launch longest-first from recorded durations; the first run
  (no data yet) uses declared order (`subprocess_order_standard`), so
  listing the slowest lanes first still helps once.
- Lane config must live in the same file that declares your pytest markers
  (`[pytest].markers`, or `[tool.pytest.ini_options].markers` in
  `pyproject.toml`).
- Lane-to-marker mapping is one marker per lane; multiple lanes may share a
  marker.
- **Third-party plugins that write one output file per session** need the
  same treatment `--junitxml` and `--cov` already get (each lane staged to
  its own path, merged afterwards). Those two are handled; a plugin writing
  its own single report file from every lane will still have its lanes race
  for it. `--cov-report` specs carrying modifiers, such as
  `term-missing:skip-covered`, are reported as unsupported and skipped —
  the combined `.coverage` is still written, so you can run `coverage`
  yourself.
- Lane children run with pytest's cacheprovider disabled (concurrent
  children would race on `.pytest_cache` and clobber each other's
  `lastfailed`), so `pytest --lf` after an orchestrated run does not see
  lane failures — use the `reproduce: pytest --lane=<name>` hint printed
  under each failed lane instead.

## Roadmap

Details and sequencing in [ROADMAP.md](https://github.com/HuzPro/pytest-lanes/blob/main/ROADMAP.md). v0.2 shipped the
bounded worker pool, the trust and debugging tools (`--lanes-explain`, a
live ETA, and reproduce hints), zero-config lanes (`--lane-def` and
`--lanes-auto`, no config file required), duration-aware scheduling
(recorded per-lane wall times drive longest-first launch and real ETAs),
and `--lanes-suggest` — a static scan that prints a proposed
`[pytest-lanes]` config from your directory layout and conftests, the
differentiator no other tool offers. Closing out the performance
milestone, it also shipped per-file run measurement, in-lane xdist
(`lane_numprocesses`), duration-balanced `--lanes-suggest` partitions,
and statically-planned [lane sharding](#sharding-splitting-a-slow-lane).

It also ships `[tool.pytest-lanes]` configuration in `pyproject.toml` —
the full lane schema, frozen for 0.x. The remaining direction is
per-lane OS gating (`requires_os`) and release-time discoverability work.

## FAQ

**Why is pytest so slow with testcontainers?**
Usually because container startup is a session fixture and the whole suite
runs in one process: each container boots, its tests run, the next boots,
and nothing overlaps. Lanes run each container-backed test directory in its
own subprocess, so those setup-then-test sequences overlap. Try
`pytest -n auto --dist loadfile` first — if per-worker duplication is
affordable for you, that is less machinery. See
[Should you use this?](#should-you-use-this).

**Why does pytest-xdist start one database container per worker?**
Session-scoped fixtures are per *process*, and every xdist worker is a
process, so eight workers touching Postgres-backed tests means eight
Postgres containers. Whether that costs you anything depends: they boot
concurrently, so wall-clock boot is roughly one container, not eight. It
hurts when setup is serialized CPU work (migrations, seeding), when eight
copies exhaust memory or connection limits, or when the resource is a
singleton that cannot be duplicated at all. In those cases lanes route
every test of an environment into one subprocess, so the setup happens
once. If a single homogeneous lane is then your bottleneck,
`lane_numprocesses` re-introduces xdist *inside* that lane only, where
you've decided duplication is affordable.

**My tests pass alone but fail under pytest-xdist.**
That is the concurrency-safety tax: any two tests can now run at the same
time, so fixed ports, shared schemas, config files, and global state
collide scheduling-dependently. You can retrofit every such test (dynamic
ports, unique names, locks) — or draw lanes along the boundaries that
already exist, so unsafe tests simply never overlap. Lanes is the "run
the suite you have today" option; see
[the measured comparison](#measured-results).

**How do I run pytest test directories in parallel as separate processes?**
That is literally this plugin: declare each directory as a lane (or run
`pytest . --lanes-auto` for one lane per test subdirectory, or
`pytest --lanes-suggest` to have the partition generated for you), and
`pytest .` fans out one subprocess per lane with a merged summary,
propagated exit codes, and per-lane reproduce commands.

**How is this different from pytest-split or pytest-shard?**
Those slice a suite across CI *machines* by recorded timing; each node
still runs its slice serially, and the slices ignore environment
boundaries. Lanes parallelize on one machine along infrastructure
boundaries. They compose: shard in CI, lanes within each node.

**Does it work on Windows?**
Yes — it is developed and benchmarked on Windows 11 and CI-tested on
Windows and Linux (Python 3.10–3.13). No `fork()`, no POSIX-only process
management.

**How many CPU cores do I need?**
Roughly one physical core per concurrent lane; the speedup is bounded by
`min(lanes, cores)`. On 1–2 core machines lanes queue (bounded worker
pool) and the run degrades toward serial — see
[Hardware requirements](#hardware-requirements).

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

[MIT](https://github.com/HuzPro/pytest-lanes/blob/main/LICENSE)
