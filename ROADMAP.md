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
declared `subprocess_order_standard` order, so for now the guidance is to
list the slowest lanes first. Real longest-first ordering waits for real
duration data — deliberately not guessed.

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

## v0.3 — Duration cache & longest-first scheduling (speed track)

Today queued lanes launch in declared order. Recorded timing turns that
into a real schedule:

- **Duration cache** — persist per-lane wall times from each run via
  pytest's `config.cache` (key `pytest-lanes/lane-durations`), the same
  idea as pytest-split's `.test_durations`. Gives the scheduler real
  numbers instead of the "list slowest first" convention.
- **`LongestFirstPolicy`** — an ordering strategy that queues the longest
  lanes first once cached data exists and falls back to declared order
  until it does. Also produces better ETAs for pending lanes.

Then, as a later opt-in on top of the cache:

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

## v0.4 — `--lanes-suggest` (DX track)

Static suggestion of a lane config for a suite that has none — the
differentiator none of the prior-art tools offer. v1 does no execution; it
reads structure only:

- Partition candidates from the directory layout under the test root(s).
- An AST scan of `conftest.py` files for session/module-scoped fixtures
  and for `testcontainers` / `docker` / DB-driver imports, to flag the
  lanes that carry expensive infrastructure.
- Existing pytest markers folded in as classification hints.

Output is a commented `[pytest-lanes]` INI block printed to stdout, framed
explicitly as a suggestion to read and adjust — then verify with
`--lanes-explain` before committing it. Resolving the real fixture-request
graph (which test actually pulls which session-scoped fixture) is out of
scope for v1: the static scan is a starting point, not an oracle.

## Also planned

- Layer `pytest-xdist` *inside* a homogeneous lane (`lane_numprocesses`).
- `pyproject.toml` (`[tool.pytest-lanes]`) configuration — deferred until
  the config schema stops churning.
- Per-lane OS gating (`requires_os`).
- Discoverability / SEO: FAQ-style README additions phrased the way people
  actually search ("pytest slow with testcontainers", "xdist starts one
  container per worker"), PyPI release with full metadata, GitHub topics —
  explicitly deferred until PyPI release time.
