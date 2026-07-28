# Changelog

## 0.3.1 - 2026-07-28

Documentation only, no code changes.

- **The README is now a short front page.** Everything deeper moved to
  [docs/GUIDE.md](https://github.com/HuzPro/pytest-lanes/blob/main/docs/GUIDE.md).
  Comments across the codebase trimmed to match.

## 0.3.0 - 2026-07-25

First published release. 0.2.0 was tagged but never uploaded; everything in
its entry below ships here too.

- **Ships type information.** The package has always been fully annotated but
  shipped no `py.typed` marker, so type checkers ignored it downstream
  (PEP 561). Added, verified present in both the wheel and the sdist, and
  declared with the `Typing :: Typed` classifier.

- **Packaging and README readiness.** Every README link is now absolute so it
  resolves on PyPI as well as GitHub (relative links silently 404 on the
  project page); `twine check` passes on both artifacts. Added a
  tag-triggered publish workflow using PyPI Trusted Publishing (no API token
  is stored in the repo) which refuses to publish when the pushed tag does
  not match the declared package version. Extended the PyPI keywords toward
  the phrases people actually search (xdist, session fixtures, integration
  testing, concurrency, test isolation) and added `Documentation`/`Source`
  project URLs.

- **README rewritten for readers rather than for completeness.** Real terminal
  screenshots (generated from actual runs, not mocked), an "is this for you?"
  decision table that names the cases where `pytest-xdist` is the better
  answer, a command-line reference table, a table of contents, and install +
  quickstart moved to the top instead of sitting behind 160 lines of
  justification.

- **Fixed: `--cov` no longer corrupts its data file or fails the run.** Every
  lane child inherited the same `COVERAGE_FILE`, so concurrent writers hit
  `coverage.exceptions.DataError: no such table: other_db.file` and a lane
  was reported as FAILED even though all of its tests passed. Each lane now
  measures into its own `.coverage.<lane>` data file; the parent runs
  `coverage combine` after the lanes finish and produces the reports that
  were requested, once, from the combined data. Child lanes no longer emit
  their own partial reports. `--cov-report` specs with modifiers
  (`term-missing:skip-covered`) are called out as unsupported and skipped
  rather than silently dropped; the combined data file is still written.

- **Fixed: `--junitxml` no longer silently discards most of the suite.** Every
  lane wrote the same path, so the last lane to finish overwrote the others
  and CI received a report containing one lane's tests with a passing exit
  code: wrong output, no warning. Lanes now write to private staging paths
  that the parent merges into the requested file, with summed `tests`,
  `failures`, `errors`, `skipped` and `time` on the root element. Both
  `--junitxml` and `--junit-xml` spellings, and repeated flags, are handled.
  A lane that dies before writing its file is skipped rather than losing the
  whole report.

- **`-s` / `--capture=no` now streams lane output live**, as it does in plain
  pytest. Previously live output was reachable only through the
  undocumented `PYTEST_LANES_SHOW_OUTPUT=1` environment variable, so `-s`
  ran but its `print()` output was swallowed for every passing lane, the
  exact output the flag exists to show. Bundled short options (`-sv`,
  `-xs`) count too. Added `--lanes-show-output` for streaming without
  disabling capture; the environment variable still works.

- **Repositioned the documentation.** The README no longer leads with being
  faster than pytest-xdist: on a concurrency-safe, balanced suite xdist is
  usually the right tool and is now recommended as the thing to try first,
  including `--dist loadgroup`, which covers much of what lanes do for
  scheduling. The case for lanes is stated as what it is: parallelism
  without retrofitting tests for concurrency-safety, a fixture lifecycle
  per group rather than per worker, and working `-s`/`--pdb`. Prior art now
  names the closest alternatives (`pytest-isolated`,
  `pytest-shared-session-scope`, Pants/Bazel/Buck2) and says when to prefer
  them.

- **Corrected an overstated claim.** The docs said per-worker infrastructure
  means "the most expensive part of the suite gets multiplied, not divided".
  That is wrong for container *boot*, which happens concurrently across
  workers: eight Postgres containers cost roughly one container's latency,
  not eight. Duplication actually hurts when setup is serialized CPU work
  (migrations, seeding, loading a model or index), when copies exhaust
  memory or connection limits, or when the resource is irreducibly
  singleton. Also documented the file-granularity floor: a suite whose time
  sits in one huge test file cannot be split further by lanes.

## 0.2.0 - 2026-07-25

- **`[tool.pytest-lanes]` configuration in `pyproject.toml`.** The full lane
  schema (index keys, lane tables as `[tool.pytest-lanes.lane.<name>]`,
  `subprocess_env_set` as a real TOML table) loading into the same
  validated config model as the INI format. Markers validate against
  `[tool.pytest.ini_options].markers` in the same file. Discovery follows
  pytest's own precedence: `pytest.ini`, then `pyproject.toml`, then
  `tox.ini`, then `setup.cfg`. The TOML loader is deliberately stricter
  than the INI one: unknown keys, ghost lane tables, and wrong TOML types
  are config errors naming the offending field, not silently ignored. On
  Python 3.10 the `tomli` backport is pulled in automatically (`tomllib`
  is stdlib from 3.11). The configuration schema (both formats) is
  frozen for the whole 0.x series: additions only, no renames or removals.

- **Fixed: filtered runs no longer crash on tests outside every lane.**
  With a lane config that declares no fallback lane, `pytest . -k <expr>`
  (or `-m`, or targeted paths: anything that makes orchestration step
  aside) used to die with an INTERNALERROR `LookupError` as soon as plain
  pytest collected a test no lane classifies (found running litestar,
  whose `docs/examples/` tests live outside its lanes). Lane marking is
  advisory when no `--lane` selection is active: unclassifiable items now
  run unmarked. Under an explicit `--lane=` selection the error stays
  loud; there it means classifiers and subprocess paths disagree.

- **Duration-balanced `--lanes-suggest`.** When recorded per-file durations
  exist, `--lanes-suggest` now prints a duration-balanced partition instead
  of the static directory scan: files pool across records (slowest
  measurement wins), pack greedily longest-first into up to
  `min(cpu_count, 8)` lanes at directory granularity (a directory heavy
  enough to unbalance the run on its own , >1.3x the per-lane target, is
  split at file level) and render as a paste-ready INI block with
  projected seconds per lane, marker declarations, and a `rest` catch-all
  lane (`classifier_fallback` + `subprocess_ignore_other_lanes` +
  `tolerate_no_tests`) so tests added after recording run instead of being
  silently skipped. The header warns that the balance sees durations only:
  files coupled to the same shared external service must be moved into one
  lane by hand. Same records, same partition: the packing is fully
  deterministic. Without recorded data the static scan still prints, now
  followed by a tip to record durations and re-run for the balanced
  version. `tolerate_no_tests` is a parsed lane key (an empty tolerant
  lane succeeds instead of failing the run).

- **Lane sharding (opt-in, statically planned).** A lane that declares
  `divisible = files` (asserting its files are mutually independent AND
  its environment can run duplicated) may be split into two shards when
  the plan simulation says it pays. Before launch, the planner replays the
  real scheduler (bounded pool, longest-first) with recorded durations,
  once unsharded and once with the candidate 2-way contiguous split of the
  single longest divisible lane; the split happens only when the projected
  makespan improves by `shard_min_saving` (default 5s) after each shard
  re-pays measured startup + collect. Same inputs, same plan, every run:
  the cut persists to `shard_plan.json` and only re-cuts (loudly) when
  durations drift beyond 20% imbalance. Shard 1 runs an explicit file
  list; shard 2 runs the lane minus those files, so files added since
  recording can never be dropped. Shards print a receipt
  (`sharded postgres into 2: ...`), appear as `postgres~1of2` rows, merge
  their measurements back into the parent lane's record, and a failed
  shard prints both `pytest --lane=<lane>` and its exact file-list
  command. `--lanes-no-shard` disables planning; no recorded data means
  no sharding, ever; `--lanes-explain` shows divisibility and the
  persisted plan.

- **In-lane xdist (`lane_numprocesses`).** A homogeneous lane can opt in
  to spreading its files across xdist workers (`-n K --dist loadfile`
  inside that lane's subprocess only). Requires pytest-xdist (a clear
  usage error otherwise). Inside such a lane, per-worker environment
  duplication and concurrency-safety obligations return; that is the
  lane's explicit trade. Per-file durations still record via the xdist
  controller.
- **`--lanes-suggest` split advice.** With recorded per-file data, the
  suggestion output now includes advice for splitting the longest lane
  into two declared lanes (balanced contiguous halves with projected
  times) shown only when half the lane's test time exceeds its measured
  fixed cost (startup + collect), which every new lane re-pays.

- **Per-file run measurement (durations v2).** Lane children now measure
  their own runs: per-file test durations, `collect` (session start to
  end of collection), and `startup` (end of collection to first test,
  which captures fixture/container spin-up), and report them to the
  parent, which merges full lane records into the duration store. v1
  duration files migrate transparently. This is the data layer for shard
  planning and `--lanes-suggest` split advice.

- **Lane children no longer touch pytest's cache** (`-p no:cacheprovider`
  in every child argv). Concurrent children racing to create
  `.pytest_cache` could break sibling collection with a transient
  `pytest-cache-files-*` directory (observed on Windows CI), and parallel
  cache writers clobbered `lastfailed` last-writer-wins anyway. Known
  trade-off: `pytest --lf` does not see failures from lane subprocesses.

- **`--lanes-suggest`.** Statically analyzes an unconfigured suite:
  directory partition plus an AST scan of each test directory's
  `conftest.py` for session/module-scoped fixtures and infrastructure
  imports (testcontainers, docker, DB drivers), and prints a commented,
  reviewable `[pytest-lanes]` INI block, infrastructure-heavy lanes
  ordered first. No user code is executed; the output is framed as a
  suggestion to verify with `--lanes-explain`, never an oracle.

- **Duration cache and longest-first scheduling.** Each orchestrated run
  records per-lane wall times to
  `.pytest_cache/v/pytest-lanes/lane_durations.json`. When recorded data
  exists, queued lanes launch longest-first instead of declared order
  (lanes without data launch first; an unmeasured lane may be the
  longest); the "list slowest lanes first" guidance is now only needed
  for the very first run. Recorded durations also feed the live ETA for
  lanes still waiting on a worker slot. A missing or corrupt cache file
  degrades to declared-order scheduling, never an error.

- **Zero-config lanes.** Two ways to get lanes with no INI file:
  `--lane-def name=path[,path...]` (repeatable) defines lanes on the
  command line (CLI definitions take precedence over INI config) and
  `--lanes-auto` derives one lane per test-bearing subdirectory of the
  rootdir (skipping hidden directories and virtualenvs), falling back to
  plain pytest with a printed notice when no usable partition exists.
  Both add an automatic fallback lane so `pytest .` still runs every
  unclaimed test; that lane may legitimately collect nothing, so its
  NO_TESTS_COLLECTED exit is treated as success. Ad-hoc lanes apply no
  markers; markers stay an INI feature.

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
  `reproduce: pytest --lane=<name>`, the exact command to re-run that lane
  in isolation, in-process.
- **Bounded worker pool.** Lanes no longer all spawn at once: at most
  `max_workers` lane subprocesses run concurrently (INI key `max_workers`
  under `[pytest-lanes]`, CLI flag `--lanes-max-workers=N`; default: CPU
  count, precedence CLI > INI > detected). Remaining lanes queue in
  declared `subprocess_order_standard` order and launch as slots free.
  Behavior change: on machines with fewer cores than lanes, runs that
  previously thrashed all subprocesses at once now queue; that is the
  fix, not a regression. Duration-aware longest-first ordering is
  deliberately deferred until recorded lane durations exist.
- New `Hardware requirements` README section: the speedup is bounded by
  `min(concurrent lanes, physical cores)`: roughly one core per
  concurrent lane.
- Version is now single-sourced from `pytest_lanes.__version__` (hatch
  dynamic versioning); ruff configured with a CI lint job.

## 0.1.0 - 2026-07-20

Initial release. Benchmarked against every pytest-xdist distribution
mode. Ships a Docker-backed example (`examples/containers`) comparing
lanes, serial, and xdist at small scale.

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
