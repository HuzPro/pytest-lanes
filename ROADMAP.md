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

## v0.3 — Trust & debugging DX (DX track)

Make the lane partition and its failures inspectable without guesswork.

- **`--lanes-explain`** — a collect-only listing of each test, the lane it
  is classified into, and the classifier rule that matched. Inspect the
  partition without running anything.
- **ETA in the live display** — wire the existing per-lane duration
  estimate into the progress display, so a run shows expected time
  remaining, not only elapsed.
- **Reproduce hints** — under each failed lane in the summary, print
  `reproduce: pytest --lane=<name>`, the exact command to re-run that lane
  in isolation.

## v0.4 — Zero-config lanes (DX track)

Today the plugin requires an INI section. Two additions remove that
requirement for the common cases:

- **`--lane-def name=path[,path...]`** (repeatable) — define lanes on the
  command line, no config file. Composes with tox commands and one-off runs:

  ```bash
  pytest --lane-def acceptance=tests/acceptance --lane-def db=tests/integration .
  ```

  CLI definitions take precedence over INI config when both exist. Ad-hoc
  lanes skip marker application (markers remain an INI feature) — they are
  purely a partition + fan-out instruction.

- **`--lanes-auto`** — one lane per immediate subdirectory of the test
  root(s), plus a fallback lane for stray files. The true drop-in mode:
  nothing to write, nothing to maintain, and the directory layout most
  projects already have becomes the partition.

`--lanes-explain` (v0.3) is how you check what `--lanes-auto` actually
decided before trusting the run.

Non-goal: positional syntax like `pytest tests/acceptance:lane-name` —
the colon collides with pytest's `file.py::test` node-id convention.

## v0.5 — Duration cache & longest-first scheduling (speed track)

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

## v0.6 — `--lanes-suggest` (DX track)

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
