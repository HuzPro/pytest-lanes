from _burn import burn

# Module import cost: real test modules pay for their import graph
# (framework + app code) in every process that collects them. Every xdist
# worker collects the whole suite; lane children import only their lane.
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
