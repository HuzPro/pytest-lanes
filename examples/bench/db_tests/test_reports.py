from _burn import burn

burn(0.4)


def test_reports_0():
    digest = burn(8)
    assert digest


def test_reports_1():
    digest = burn(6)
    assert digest


def test_reports_2():
    digest = burn(4)
    assert digest
