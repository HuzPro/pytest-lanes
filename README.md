# pytest-lanes

[![tests](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml/badge.svg)](https://github.com/HuzPro/pytest-lanes/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-lanes.svg?cacheSeconds=3600)](https://pypi.org/project/pytest-lanes/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-lanes.svg?cacheSeconds=3600)](https://pypi.org/project/pytest-lanes/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/HuzPro/pytest-lanes/blob/main/LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Parallel pytest for suites that cannot be made concurrency-safe.**

A **lane** is a group of tests that share a marker and an execution
environment. Each lane runs as its own pytest subprocess: it starts its
environment once, runs its tests in declaration order, and overlaps only
with *other* lanes. Nothing inside a lane ever needs to be made
concurrency-proof.

<img src="https://raw.githubusercontent.com/HuzPro/pytest-lanes/main/docs/lane-run.svg" alt="pytest-lanes running four lanes in parallel: db~1of2, db~2of2, unit and api, finishing in 49.10s against 142.51s of serial subprocess time, a 2.90x parallelism ratio" width="100%">

## Is this for you?

| Your situation | What to reach for |
|---|---|
| Homogeneous, independent, CPU-bound unit tests | **`pytest-xdist`.** It will beat this. |
| Grouping needs fit `--dist loadfile` / `loadscope` / `loadgroup` | **`pytest-xdist`.** Try it first. |
| Tests share fixed ports, one DB schema, OS state, a licensed simulator, and retrofitting them all is not happening | **pytest-lanes.** Safe orderings become structural instead of a per-test obligation. |
| You need setup/teardown per *group*, not per worker | **pytest-lanes.** A lane is the process, so its session fixtures wrap exactly its own tests. |
| Expensive setup can't be duplicated or serialized cheaply (a 4 GB model, an in-process index, one container) | **pytest-lanes.** |
| Most of your suite's time sits in one huge test file | **`pytest-xdist`.** A file is a lane's atomic unit, so that file is your floor. |

The reasoning behind this table, with measured results, lives in the
[guide](https://github.com/HuzPro/pytest-lanes/blob/main/docs/GUIDE.md).

## Install

```bash
pip install pytest-lanes[rich]     # rich gives the live progress table
```

## Quickstart

You do not have to write a partition by hand:

```bash
pytest --lanes-suggest    # propose a lane config from your layout, run nothing
pytest . --lanes-auto     # zero config: one lane per test subdirectory
pytest . --lanes-explain  # show which lane claims each test, run nothing
pytest .                  # fan out: one subprocess per lane, in parallel
```

Paste the suggestion into `pytest.ini` or `pyproject.toml` when you are
happy with it. A durable config looks like:

```ini
[pytest]
markers =
    postgres_integration: postgres-backed integration tests
    unit: fast unit tests

[pytest-lanes]
lanes = postgres other
subprocess_order_standard = postgres other

[pytest-lanes:postgres]
marker = postgres_integration
classifier_path_prefixes = tests/integration/
subprocess_paths = tests/integration

[pytest-lanes:other]
marker = unit
classifier_fallback = true
subprocess_ignore_other_lanes = true
```

With no lane config the plugin is dormant, and `pytest -k foo`,
`pytest -m unit`, or `pytest path/to/test.py` always run as plain pytest.
`-s` and `--pdb` keep working: lane output streams live under `-s`, and
`pytest --lane=<name>` runs one lane in-process where `--pdb` behaves
normally.

## Documentation

- [Guide](https://github.com/HuzPro/pytest-lanes/blob/main/docs/GUIDE.md):
  when to use it, measured results, defining lanes, the full configuration
  and command-line references, how it works, coverage and JUnit in CI,
  sharding, limitations, FAQ.
- Runnable examples:
  [`examples/demo`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/demo)
  (no Docker, 30 seconds),
  [`examples/containers`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/containers)
  (real Postgres testcontainers),
  [`examples/bench`](https://github.com/HuzPro/pytest-lanes/tree/main/examples/bench)
  (a benchmark suite comparing execution modes).
- [CHANGELOG](https://github.com/HuzPro/pytest-lanes/blob/main/CHANGELOG.md)
  and [ROADMAP](https://github.com/HuzPro/pytest-lanes/blob/main/ROADMAP.md).

## Development

```bash
git clone https://github.com/HuzPro/pytest-lanes
cd pytest-lanes
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e .[test]
pytest
```

## License

[MIT](https://github.com/HuzPro/pytest-lanes/blob/main/LICENSE)
