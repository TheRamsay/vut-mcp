from vut_mcp import context


def test_get_studis_client_returns_fresh_client(monkeypatch) -> None:
    created_clients: list[object] = []

    class FakeStudisClient:
        def __init__(self) -> None:
            created_clients.append(self)

    monkeypatch.setattr(context, "StudisClient", FakeStudisClient)

    first = context.get_studis_client()
    second = context.get_studis_client()

    assert first is not second
    assert created_clients == [first, second]
