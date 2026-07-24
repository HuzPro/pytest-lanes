from _burn import burn

# Module import cost: real test modules pay for their import graph
# (framework + app code) in every process that collects them. Every xdist
# worker collects the whole suite; lane children import only their lane.
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
