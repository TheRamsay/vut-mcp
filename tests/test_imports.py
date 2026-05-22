def test_imports() -> None:
    import vut_mcp.server
    import vut_studis

    assert vut_mcp.server.mcp is not None
    assert vut_studis.StudisClient is not None
