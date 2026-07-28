from _burn import burn

burn(0.4)


def test_ingest_0():
    digest = burn(6)
    assert digest


def test_ingest_1():
    digest = burn(4)
    assert digest


def test_ingest_2():
    digest = burn(2)
    assert digest
