# Containers example: lanes vs test-level distribution

This example reproduces, at miniature scale, the suite shape pytest-lanes is
built for — and lets you measure it on your own machine.

It has two kinds of tests:

- **`db_tests/`** — four modules of real Postgres integration tests. They
  share one `postgres:16-alpine` container through a **per-process
  singleton** (started on first use, reused by every module — the standard
  session-container pattern). Each module also holds a **fixed localhost
  port** for its duration, simulating a daemon that owns one well-known
  port.
- **`unit_tests/`** — fast, dependency-free tests.

## Run it

Docker must be running.

```bash
pip install -r requirements.txt
cd examples/containers
pytest .            # lanes: db subprocess + unit subprocess in parallel
python bench.py     # times lanes vs serial vs xdist on the same suite
```

## What you should see

A run on a mid-range machine (first run adds a one-time image pull):

```
mode              wall (median)   passed   failed
lanes                     4.1s       14        0
serial                    3.7s       14        0
xdist-load                5.4s        5        9
xdist-loadfile            5.7s        6        8
```

- **lanes** — two subprocesses: the db lane starts *one* container and runs
  its modules sequentially (the fixed port binds and releases cleanly);
  the unit lane finishes in parallel. All tests pass.
- **serial** — same single container, everything queued. At 14 tests it
  even beats lanes slightly: parallelism can't pay for two subprocess
  startups on a suite this small. The speed dimension needs scale — the
  main README benchmarks a ~2,430-test suite where lanes win by 2.1x.
  What this example isolates is the *mechanics*.
- **xdist** — every worker that picks up a db module starts **its own
  container** (the singleton lives per process), multiplying the most
  expensive fixture instead of sharing it. And whenever two db modules run
  concurrently, they collide on the fixed port: most of the suite fails,
  and *which* tests fail changes run to run, because correctness now
  depends on where the scheduler happened to place them.

`--dist loadfile` keeps each *module* on one worker but still lets two
different db modules overlap; only `--dist loadgroup` with a hand-written
`xdist_group` mark on every db test pins them all to one worker — at which
point you have re-implemented a lane by hand, minus the isolated process,
the config-driven classification, and the per-lane reporting.
