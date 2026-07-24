# Changelog

## 0.2.0 — unreleased

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
