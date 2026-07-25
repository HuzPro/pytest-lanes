# Changelog

## 0.2.0 — 2026-07-25

- **`[tool.pytest-lanes]` configuration in `pyproject.toml`.** The full lane
  schema — index keys, lane tables as `[tool.pytest-lanes.lane.<name>]`,
  `subprocess_env_set` as a real TOML table — loading into the same
  validated config model as the INI format. Markers validate against
  `[tool.pytest.ini_options].markers` in the same file. Discovery follows
  pytest's own precedence: `pytest.ini`, then `pyproject.toml`, then
  `tox.ini`, then `setup.cfg`. The TOML loader is deliberately stricter
  than the INI one: unknown keys, ghost lane tables, and wrong TOML types
  are config errors naming the offending field, not silently ignored. On
  Python 3.10 the `tomli` backport is pulled in automatically (`tomllib`
  is stdlib from 3.11). The configuration schema — both formats — is
  frozen for the 0.2.x series: additions only, no renames or removals.

- **Fixed: filtered runs no longer crash on tests outside every lane.**
  With a lane config that declares no fallback lane, `pytest . -k <expr>`
  (or `-m`, or targeted paths — anything that makes orchestration step
  aside) used to die with an INTERNALERROR `LookupError` as soon as plain
  pytest collected a test no lane classifies (found running litestar,
  whose `docs/examples/` tests live outside its lanes). Lane marking is
  advisory when no `--lane` selection is active: unclassifiable items now
  run unmarked. Under an explicit `--lane=` selection the error stays
  loud — there it means classifiers and subprocess paths disagree.

- **Duration-balanced `--lanes-suggest`.** When recorded per-file durations
  exist, `--lanes-suggest` now prints a duration-balanced partition instead
  of the static directory scan: files pool across records (slowest
  measurement wins), pack greedily longest-first into up to
  `min(cpu_count, 8)` lanes at directory granularity — a directory heavy
  enough to unbalance the run on its own (>1.3x the per-lane target) is
  split at file level — and render as a paste-ready INI block with
  projected seconds per lane, marker declarations, and a `rest` catch-all
  lane (`classifier_fallback` + `subprocess_ignore_other_lanes` +
  `tolerate_no_tests`) so tests added after recording run instead of being
  silently skipped. The header warns that the balance sees durations only:
  files coupled to the same shared external service must be moved into one
  lane by hand. Same records, same partition — the packing is fully
  deterministic. Without recorded data the static scan still prints, now
  followed by a tip to record durations and re-run for the balanced
  version. `tolerate_no_tests` is a parsed lane key (an empty tolerant
  lane succeeds instead of failing the run).

- **Lane sharding (opt-in, statically planned).** A lane that declares
  `divisible = files` — asserting its files are mutually independent AND
  its environment can run duplicated — may be split into two shards when
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
  duplication and concurrency-safety obligations return — that is the
  lane's explicit trade. Per-file durations still record via the xdist
  controller.
- **`--lanes-suggest` split advice.** With recorded per-file data, the
  suggestion output now includes advice for splitting the longest lane
  into two declared lanes — balanced contiguous halves with projected
  times — shown only when half the lane's test time exceeds its measured
  fixed cost (startup + collect), which every new lane re-pays.

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
