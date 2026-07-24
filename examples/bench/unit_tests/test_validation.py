from _burn import burn

# Module import cost: real test modules pay for their import graph
# (framework + app code) in every process that collects them. Every xdist
# worker collects the whole suite; lane children import only their lane.
burn(0.4)


def test_validation_0():
    digest = burn(2)
    assert digest


def test_validation_1():
    digest = burn(2)
    assert digest


def test_validation_2():
    digest = burn(1)
    assert digest
