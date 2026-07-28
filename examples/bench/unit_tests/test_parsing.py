from _burn import burn

burn(0.4)


def test_parsing_0():
    digest = burn(2)
    assert digest


def test_parsing_1():
    digest = burn(1)
    assert digest


def test_parsing_2():
    digest = burn(1)
    assert digest
