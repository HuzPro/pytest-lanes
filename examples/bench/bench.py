"""Benchmark the execution modes on the representative suite in this directory."""

from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
DISABLE_PLUGIN_ENV = {"PYTEST_LANES_CHILD": "1"}


def _mode_commands() -> dict[str, tuple[list[str], dict[str, str], str | None]]:
    """mode -> (argv, extra_env, ini_variant_or_None)."""
    pytest_cmd = [sys.executable, "-m", "pytest", ".", "-q", "--color=no"]
    return {
        "serial": (pytest_cmd, DISABLE_PLUGIN_ENV, None),
        "xdist-load": ([*pytest_cmd, "-n", "auto"], DISABLE_PLUGIN_ENV, None),
        "xdist-loadfile": (
            [*pytest_cmd, "-n", "auto", "--dist", "loadfile"],
            DISABLE_PLUGIN_ENV,
            None,
        ),
        "lanes": (pytest_cmd, {}, "ini_plain.ini"),
        "lanes-opt": (pytest_cmd, {}, "ini_optimized.ini"),
    }


def _run_mode(argv: list[str], extra_env: dict[str, str], ini: str | None) -> float:
    if ini is not None:
        shutil.copyfile(HERE / ini, HERE / "pytest.ini")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **extra_env}
    env.pop("PYTEST_LANES_DURATIONS_OUT", None)
    if not extra_env:
        env.pop("PYTEST_LANES_CHILD", None)

    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise SystemExit(
            f"mode failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
        )
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    modes = _mode_commands()
    print(f"warm-up: one untimed run per mode ({len(modes)} modes)")
    for name, (argv, env, ini) in modes.items():
        _run_mode(argv, env, ini)
        print(f"  warmed {name}")

    timings: dict[str, list[float]] = {name: [] for name in modes}
    for round_index in range(args.runs):
        for name, (argv, env, ini) in modes.items():
            elapsed = _run_mode(argv, env, ini)
            timings[name].append(elapsed)
            print(f"round {round_index + 1}: {name:<15} {elapsed:7.1f}s")

    shutil.copyfile(HERE / "ini_plain.ini", HERE / "pytest.ini")

    print(f"\n{'mode':<15} {'median':>8} {'min':>8} {'max':>8}")
    for name, samples in timings.items():
        print(
            f"{name:<15} {statistics.median(samples):>7.1f}s "
            f"{min(samples):>7.1f}s {max(samples):>7.1f}s"
        )


if __name__ == "__main__":
    main()
