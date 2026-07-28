from _burn import burn

burn(0.4)


def test_routes_0():
    digest = burn(4)
    assert digest


def test_routes_1():
    digest = burn(3)
    assert digest


def test_routes_2():
    digest = burn(2)
    assert digest
