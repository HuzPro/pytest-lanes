from _burn import burn

burn(0.4)


def test_validation_0():
    digest = burn(2)
    assert digest


def test_validation_1():
    digest = burn(2)
    assert digest


def test_validation_2():
    digest = burn(1)
    assert digest
