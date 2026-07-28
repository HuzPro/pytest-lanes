"""Calibrated CPU work standing in for real test computation."""

import hashlib

_ITERATIONS_PER_UNIT = 3_400_000


def burn(units: float) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", b"pytest-lanes-bench", b"salt", int(units * _ITERATIONS_PER_UNIT)
    )
