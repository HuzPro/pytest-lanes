from _burn import burn

burn(0.4)


def test_rounding_0():
    digest = burn(1)
    assert digest


def test_rounding_1():
    digest = burn(1)
    assert digest


def test_rounding_2():
    digest = burn(1)
    assert digest
