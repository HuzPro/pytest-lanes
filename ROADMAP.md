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

## Later — lane sharding (load balancing)

An opt-in on top of the duration cache:

- **Lane sharding (load balancing)** — when a worker goes idle and a
  divisible lane still has queued work, move file-sized shards of it onto
  the idle worker. The move only pays when
  `remaining lane time > environment spin-up cost + collection cost`, so
  the balancer must price each lane's fixed costs (a Postgres container
  is ~5-7s; the cache provides the numbers).

  **Correctness constraint (hard requirement):** sharding is opt-in per
  lane (`divisible = files`). Splitting a lane redistributes execution
  order across processes — exactly the failure mode measured in the
  README's `loadgroup` row, where per-test grouping produced 2–16
  scheduling-dependent failures per run. File granularity plus explicit
  opt-in keeps the "the only concurrency is the concurrency you
  declared" property intact.

## Also planned

- Layer `pytest-xdist` *inside* a homogeneous lane (`lane_numprocesses`).
- `pyproject.toml` (`[tool.pytest-lanes]`) configuration — deferred until
  the config schema stops churning.
- Per-lane OS gating (`requires_os`).
- Discoverability / SEO: FAQ-style README additions phrased the way people
  actually search ("pytest slow with testcontainers", "xdist starts one
  container per worker"), PyPI release with full metadata, GitHub topics —
  explicitly deferred until PyPI release time.
