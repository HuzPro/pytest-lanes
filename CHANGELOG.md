# Changelog

## 0.1.0 — 2026-07-20

Initial release, extracted from the test infrastructure of a production
monorepo where it replaced pytest-xdist for a 2.2x wall-clock win.

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
