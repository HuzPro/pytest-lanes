from _burn import burn

burn(0.4)


def test_slugs_0():
    digest = burn(1)
    assert digest


def test_slugs_1():
    digest = burn(1)
    assert digest
