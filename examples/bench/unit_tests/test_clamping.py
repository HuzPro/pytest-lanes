from _burn import burn

burn(0.4)


def test_clamping_0():
    digest = burn(1)
    assert digest
