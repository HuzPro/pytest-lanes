from _burn import burn

burn(0.4)


def test_orders_0():
    digest = burn(4)
    assert digest


def test_orders_1():
    digest = burn(3)
    assert digest


def test_orders_2():
    digest = burn(2)
    assert digest
