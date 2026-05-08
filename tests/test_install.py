def test_import():
    import africalim

    assert hasattr(africalim, "__version__")


def test_version_is_string():
    from africalim import __version__

    assert isinstance(__version__, str)
