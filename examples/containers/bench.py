"""Time this example suite under lanes, serial pytest, and xdist modes.

Run from this directory: ``python bench.py`` (add ``--runs N`` for more
rounds). Docker must be running. xdist modes are skipped when pytest-xdist
is not installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import statistics
import subprocess
import sys
import time

CHILD_ENV = "PYTEST_LANES_CHILD"

MODES: dict[str, dict] = {
    "lanes": {"args": ["."], "disable_plugin": False, "needs_xdist": False},
    "serial": {"args": ["."], "disable_plugin": True, "needs_xdist": False},
    "xdist-load": {"args": [".", "-n", "auto"], "disable_plugin": True, "needs_xdist": True},
    "xdist-loadfile": {
        "args": [".", "-n", "auto", "--dist", "loadfile"],
        "disable_plugin": True,
        "needs_xdist": True,
    },
}

_COUNT_PATTERN = re.compile(r"(\d+) (passed|failed|error)")


def _run_once(mode: dict) -> tuple[float, int, int]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if mode["disable_plugin"]:
        env[CHILD_ENV] = "1"
    else:
        env.pop(CHILD_ENV, None)

    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *mode["args"]],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    wall = time.perf_counter() - start

    passed = failed = 0
    output = (proc.stdout or "") + (proc.stderr or "")
    for line in reversed(output.splitlines()):
        matches = _COUNT_PATTERN.findall(line)
        if matches and " in " in line or "Total:" in line:
            for count, label in matches:
                if label == "passed":
                    passed = int(count)
                else:
                    failed += int(count)
            break
    return wall, passed, failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    have_xdist = importlib.util.find_spec("xdist") is not None
    print(f"{'mode':<16}{'wall (median)':>15}{'passed':>9}{'failed':>9}")
    for name, mode in MODES.items():
        if mode["needs_xdist"] and not have_xdist:
            print(f"{name:<16}{'skipped (no pytest-xdist)':>15}")
            continue
        walls, last_passed, last_failed = [], 0, 0
        for _ in range(args.runs):
            wall, last_passed, last_failed = _run_once(mode)
            walls.append(wall)
        print(
            f"{name:<16}{statistics.median(walls):>13.1f}s{last_passed:>9}{last_failed:>9}",
            flush=True,
        )


if __name__ == "__main__":
    main()
