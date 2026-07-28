from _burn import burn

burn(0.4)


def test_streaming_0():
    digest = burn(3)
    assert digest


def test_streaming_1():
    digest = burn(2)
    assert digest


def test_streaming_2():
    digest = burn(1)
    assert digest
