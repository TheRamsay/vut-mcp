def test_imports() -> None:
    import vut_mcp.server
    import vut_studis

    assert vut_mcp.server.mcp is not None
    assert vut_studis.StudisClient is not None


def test_studis_transport_imports() -> None:
    from vut_studis.transport import StudisTransport

    assert StudisTransport.__name__ == "StudisTransport"


def test_moodle_client_is_publicly_importable() -> None:
    from vut_moodle import MoodleClient

    assert MoodleClient.__name__ == "MoodleClient"
