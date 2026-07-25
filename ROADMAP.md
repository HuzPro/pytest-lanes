# Roadmap

Direction: the two things that matter most, in order, are (1) verifiable
speedup and (2) ease of use — "drop in, immediate speed boost." Every item
below serves one of those.

## Shipped in v0.2 — bounded worker pool

Lanes no longer all spawn at once. At most `max_workers` lane subprocesses
run concurrently; the rest queue and launch as slots free. The count comes
from the `max_workers` INI key under `[pytest-lanes]` or the
`--lanes-max-workers=N` flag — default `os.cpu_count()`, precedence CLI >
INI > detected CPU count, values <= 0 rejected. Queued lanes launch in
declared `subprocess_order_standard` order on the first run, and
longest-first once the duration cache (below) has data.

### Also in v0.2 — trust & debugging DX

The lane partition and its failures are now inspectable without guesswork.

- **`--lanes-explain`** — a collect-only listing of each test, its lane,
  and the classifier rule that matched. Inspect the partition without
  running anything; it shares one code path with real classification, so
  the listing cannot drift.
- **ETA in the live display** — the per-lane duration estimate now drives
  an expected-time-remaining readout, not only elapsed time.
- **Reproduce hints** — each failed lane in the summary is now followed by
  `reproduce: pytest --lane=<name>`, the exact command to re-run it in
  isolation.

### Also in v0.2 — zero-config lanes

The plugin no longer needs an INI section for the common cases. Two flags
define lanes with no config file, and both compose with `--lane=`,
`--lanes-explain`, and `--lanes-max-workers`:

- **`--lane-def name=path[,path...]`** (repeatable) — defines a lane on the
  command line, claiming its paths as classifier prefixes and subprocess
  paths. An automatic `other` fallback lane always claims whatever no
  definition matched; it may legitimately collect nothing, and that empty
  `NO_TESTS_COLLECTED` counts as success. CLI definitions take precedence
  over INI entirely. Ad-hoc lanes apply no markers (markers stay an INI
  feature); malformed defs, duplicates, and the reserved name `other` are
  usage errors.

  ```bash
  pytest . --lane-def db=tests/integration --lane-def api=tests/api,tests/contracts
  ```

- **`--lanes-auto`** — one lane per immediate subdirectory of the rootdir
  that contains test files, sorted alphabetically; dot-directories,
  `__pycache__`, and virtualenvs are never lanes, and stray root-level tests
  fall to the fallback lane. If fewer than two subdirectory lanes exist it
  prints `pytest-lanes: --lanes-auto found no test-bearing subdirectory
  partition; running plain pytest.` and steps aside — it never pretends to
  parallelize a partition of one. Activates only on the explicit flag.

`--lanes-explain` (shipped above) is how you verify what `--lanes-auto`
decided before trusting the run. Non-goal: positional syntax like `pytest
tests/acceptance:lane-name` — the colon collides with pytest's
`file.py::test` node-id convention.

### Also in v0.2 — duration cache & longest-first scheduling

Queued lanes now launch on real timing instead of the "list slowest first"
convention.

- **Duration cache** — each run records per-lane wall times to
  `.pytest_cache/v/pytest-lanes/lane_durations.json` (under pytest's
  cache directory), merged with prior data; a missing or corrupt file
  degrades to "no data" rather than erroring.
- **Longest-first scheduling** — once recorded data exists, queued lanes
  launch longest-first instead of declared order. Lanes with no recorded
  duration launch first, keeping their declared relative order — an
  unmeasured lane may be the longest, so starting it early is the safe
  bet. The first run (no data yet) uses declared
  `subprocess_order_standard` order. Recorded durations also feed the live
  ETA: lanes still queued for a slot contribute their recorded duration to
  the estimated-time-remaining readout.

### Also in v0.2 — `--lanes-suggest`

The plugin can now propose a lane config for a suite that has none — the
differentiator none of the prior-art tools offer. It executes no test
code; it reads structure only:

- The directory partition — one candidate lane per test-bearing
  subdirectory, the same rules as `--lanes-auto`.
- An AST scan of each test directory's `conftest.py` files for
  session/module/package-scoped fixtures and infrastructure imports
  (`testcontainers`, `docker`, and the Postgres / MySQL / SQLAlchemy /
  Redis / Kafka / Mongo / boto3 drivers), used to order the
  infrastructure-heavy lanes first under a slowest-first heuristic.

Output is a commented `[pytest-lanes]` INI block on stdout — a
`[pytest].markers` block, the index section (the fallback `other` lane
appears in `subprocess_order_standard` only when stray root-level tests
exist), and one section per lane with a `# detected: ...` note — then
exits 0 without running tests. It is framed explicitly as a suggestion to
review and verify with `--lanes-explain`; with fewer than two test-bearing
subdirectories it prints an honest "no partition found" message instead of
guessing. Resolving the real fixture-request graph (which test actually
pulls which session-scoped fixture) is out of scope by design: the static
scan is a starting point, not an oracle. Output is ASCII-only for legacy
Windows consoles.

### Also in v0.2 — lane sharding & in-lane xdist

The performance milestone shipped, resolving the design debate this
section used to hold. Two opt-in features let a single lane stop bounding
the run, both built on the per-file duration data (durations v2) recorded
this release.

- **Lane sharding** — a lane that declares `divisible = files` may be
  split into two shards that run as separate subprocesses. The plan is
  static, computed before launch: the planner replays the real scheduler
  (bounded pool, longest-first) with recorded durations, once with every
  lane whole and once with a 2-way contiguous split of the single longest
  divisible lane, and keeps the split only when projected makespan
  improves by at least `shard_min_saving` (default 5s) after each shard
  re-pays its measured startup + collect. Scope is deliberately narrow:
  K=2, one lane per run, static-only (no live migration onto idle
  workers), and never on the first run — no recorded data, no split. The
  cut is deterministic, persisted to `shard_plan.json`, and re-cut (loudly)
  only when durations drift past 20% imbalance.

  **Correctness constraint (held):** sharding is opt-in per lane and
  always at file granularity, so redistributing files across shards never
  reorders within a file and keeps the "the only concurrency is the
  concurrency you declared" property intact — the failure mode measured in
  the README's `loadgroup` row.

  **The honest ceiling:** for a longest lane `D1 = E + T` (fixed
  environment cost plus test time) and a second-longest lane `D2`, a
  single 2-way split saves at most `min(T/2, D1 - D2)`. On a balanced
  suite the gap term makes sharding alone nearly worthless — shrink the
  runner-up first (often via `lane_numprocesses`), then the split pays.

- **In-lane xdist (`lane_numprocesses`)** — a homogeneous lane can opt in
  to `-n N --dist loadfile` inside its own subprocess, the built-in way to
  spread tests within one environment. The trade is explicit: per-worker
  environment duplication and concurrency-safety obligations return inside
  that lane. Composes with sharding — lowering the runner-up is what makes
  splitting the longest lane worthwhile.

## Also planned

- ~~`pyproject.toml` (`[tool.pytest-lanes]`) configuration~~ — **shipped in
  0.2.0**, full schema with strict TOML validation; the configuration
  schema (both formats) is frozen for the 0.2.x series.
- Per-lane OS gating (`requires_os`).
- Discoverability / SEO: FAQ-style README additions phrased the way people
  actually search ("pytest slow with testcontainers", "xdist starts one
  container per worker"), PyPI release with full metadata, GitHub topics —
  explicitly deferred until PyPI release time.
