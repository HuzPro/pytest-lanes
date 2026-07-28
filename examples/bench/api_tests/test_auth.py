from _burn import burn

burn(0.4)


def test_auth_0():
    digest = burn(2)
    assert digest


def test_auth_1():
    digest = burn(1)
    assert digest


def test_auth_2():
    digest = burn(1)
    assert digest
