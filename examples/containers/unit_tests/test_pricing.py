"""Fast, dependency-free tests: the fallback lane."""


def _discounted(price: float, percent: int) -> float:
    return round(price * (100 - percent) / 100, 2)


def test_zero_discount_keeps_price() -> None:
    assert _discounted(80.0, 0) == 80.0


def test_half_discount_halves_price() -> None:
    assert _discounted(80.0, 50) == 40.0


def test_full_discount_is_free() -> None:
    assert _discounted(80.0, 100) == 0.0


def test_discount_rounds_to_cents() -> None:
    assert _discounted(9.99, 33) == 6.69
