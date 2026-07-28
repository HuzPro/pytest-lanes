from _burn import burn

burn(0.4)


def test_audit_0():
    digest = burn(2)
    assert digest


def test_audit_1():
    digest = burn(1)
    assert digest


def test_audit_2():
    digest = burn(1)
    assert digest
