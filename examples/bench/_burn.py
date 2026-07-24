"""Calibrated CPU work standing in for real test computation.

One unit is ~1 second of single-core work on the reference machine
(Ryzen 5 7600); everything scales uniformly elsewhere, so mode-to-mode
ratios transfer. Unlike sleeps, this contends for physical cores — which
is what makes worker oversubscription and duplicated environments cost
what they cost in real suites.
"""

import hashlib

_ITERATIONS_PER_UNIT = 3_400_000


def burn(units: float) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", b"pytest-lanes-bench", b"salt", int(units * _ITERATIONS_PER_UNIT)
    )
