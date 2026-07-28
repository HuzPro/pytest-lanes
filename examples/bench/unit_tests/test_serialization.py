from _burn import burn

burn(0.4)


def test_serialization_0():
    digest = burn(2)
    assert digest


def test_serialization_1():
    digest = burn(1)
    assert digest


def test_serialization_2():
    digest = burn(1)
    assert digest
