# Roadmap

Direction: the two things that matter most, in order, are (1) verifiable
speedup and (2) ease of use — "drop in, immediate speed boost." Every item
below serves one of those.

## v0.2 — Zero-config lanes (DX track)

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

Non-goal: positional syntax like `pytest tests/acceptance:lane-name` —
the colon collides with pytest's `file.py::test` node-id convention.

## v0.3 — Duration-aware scheduling and load balancing (speed track)

The current model spawns every subprocess lane at once and the slowest
lane bounds the wall-clock. Three stages, each independently shippable:

1. **Bounded worker pool** — `max_workers` (default: CPU count), lanes
   queued longest-first using recorded durations. This is what makes the
   plugin behave sensibly on 2-core CI runners, where spawning five
   subprocesses at once just thrashes.
2. **Duration cache** — persist per-file wall times from each run (same
   idea as pytest-split's `.test_durations`), giving the scheduler real
   data instead of guesses.
3. **Lane sharding (load balancing)** — when a worker goes idle and a
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
- `pyproject.toml` (`[tool.pytest-lanes]`) configuration.
- Per-lane OS gating (`requires_os`).
- Discoverability: FAQ-style README additions phrased the way people
  actually search ("pytest slow with testcontainers", "xdist starts one
  container per worker"), PyPI release with full metadata, GitHub topics.
