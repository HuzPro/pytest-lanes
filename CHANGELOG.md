# Changelog

## 0.2.0 — unreleased

- **Per-file run measurement (durations v2).** Lane children now measure
  their own runs — per-file test durations, `collect` (session start to
  end of collection), and `startup` (end of collection to first test,
  which captures fixture/container spin-up) — and report them to the
  parent, which merges full lane records into the duration store. v1
  duration files migrate transparently. This is the data layer for shard
  planning and `--lanes-suggest` split advice.

- **Lane children no longer touch pytest's cache** (`-p no:cacheprovider`
  in every child argv). Concurrent children racing to create
  `.pytest_cache` could break sibling collection with a transient
  `pytest-cache-files-*` directory (observed on Windows CI), and parallel
  cache writers clobbered `lastfailed` last-writer-wins anyway. Known
  trade-off: `pytest --lf` does not see failures from lane subprocesses.

- **`--lanes-suggest`.** Statically analyzes an unconfigured suite —
  directory partition plus an AST scan of each test directory's
  `conftest.py` for session/module-scoped fixtures and infrastructure
  imports (testcontainers, docker, DB drivers) — and prints a commented,
  reviewable `[pytest-lanes]` INI block, infrastructure-heavy lanes
  ordered first. No user code is executed; the output is framed as a
  suggestion to verify with `--lanes-explain`, never an oracle.

- **Duration cache and longest-first scheduling.** Each orchestrated run
  records per-lane wall times to
  `.pytest_cache/v/pytest-lanes/lane_durations.json`. When recorded data
  exists, queued lanes launch longest-first instead of declared order
  (lanes without data launch first — an unmeasured lane may be the
  longest); the "list slowest lanes first" guidance is now only needed
  for the very first run. Recorded durations also feed the live ETA for
  lanes still waiting on a worker slot. A missing or corrupt cache file
  degrades to declared-order scheduling, never an error.

- **Zero-config lanes.** Two ways to get lanes with no INI file:
  `--lane-def name=path[,path...]` (repeatable) defines lanes on the
  command line — CLI definitions take precedence over INI config — and
  `--lanes-auto` derives one lane per test-bearing subdirectory of the
  rootdir (skipping hidden directories and virtualenvs), falling back to
  plain pytest with a printed notice when no usable partition exists.
  Both add an automatic fallback lane so `pytest .` still runs every
  unclaimed test; that lane may legitimately collect nothing, so its
  NO_TESTS_COLLECTED exit is treated as success. Ad-hoc lanes apply no
  markers — markers stay an INI feature.

- **`--lanes-explain`.** Lists each collected test, the lane that claimed
  it, and the classifier rule that matched (e.g.
  `io_tests/test_io.py::test_x -> io (classifier_path_prefixes: io_tests/)`),
  then exits without running anything. Classification and explanation share
  a single code path, so the listing can never drift from what actually
  runs.
- **ETA in the live display.** The progress table (rich) and the plain
  snapshot header now show estimated time remaining, from per-lane progress
  percentages and completed-lane durations.
- **Reproduce hints.** Each failed lane in the summary now prints
  `reproduce: pytest --lane=<name>` — the exact command to re-run that lane
  in isolation, in-process.
- **Bounded worker pool.** Lanes no longer all spawn at once: at most
  `max_workers` lane subprocesses run concurrently (INI key `max_workers`
  under `[pytest-lanes]`, CLI flag `--lanes-max-workers=N`; default: CPU
  count, precedence CLI > INI > detected). Remaining lanes queue in
  declared `subprocess_order_standard` order and launch as slots free.
  Behavior change: on machines with fewer cores than lanes, runs that
  previously thrashed all subprocesses at once now queue — that is the
  fix, not a regression. Duration-aware longest-first ordering is
  deliberately deferred until recorded lane durations exist.
- New `Hardware requirements` README section: the speedup is bounded by
  `min(concurrent lanes, physical cores)` — roughly one core per
  concurrent lane.
- Version is now single-sourced from `pytest_lanes.__version__` (hatch
  dynamic versioning); ruff configured with a CI lint job.

## 0.1.0 — 2026-07-20

Initial release, extracted from the test infrastructure of a production
monorepo.

Benchmarked against every pytest-xdist distribution mode on that suite
(~2,430 tests, two Docker database lanes): ~2.1x over serial pytest,
1.15x–1.3x over tuned xdist, zero failures and lowest variance of any mode
— full methodology and honest caveats in the README. Ships a
Docker-backed example (`examples/containers`) reproducing the comparison
at small scale.

- Lane classification by exact path, path prefix, path suffix, test-class
  base name, and a fallback lane.
- Subprocess fan-out: one `python -m pytest` child per lane, run in
  parallel with live progress display (rich table when `rich` is
  installed, plain text otherwise) and an aggregated summary with a
  parallelism ratio.
- `--lane=<name>[,<name>...]` for in-process single-lane runs.
- `--lanes-full` to include optional lanes (e.g. slow build-verification).
- Orchestration steps aside automatically for `-k`, `-m`, `--lf`/`--ff`,
  explicit path targets, and inside lane child processes.
- Configuration in `pytest.ini`, `tox.ini`, or `setup.cfg` under
  `[pytest-lanes]` sections; the plugin is dormant when no section exists.
- Per-lane environment overrides (`subprocess_env_set`) applied in both
  subprocess and in-process modes.
