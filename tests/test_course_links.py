import pytest

from vut_studis.client import StudisClient
from vut_studis.config import Settings


@pytest.mark.asyncio
async def test_get_course_detail_urls_uses_public_client_api(monkeypatch) -> None:
    html = """
    <table>
      <tr>
        <td>ABC</td><td>Test Course</td><td>cs</td><td>P</td><td>5</td>
        <td>ano</td><td>zk</td><td>ne</td><td></td><td></td><td></td><td></td>
        <td><a href="student.phtml?sn=predmet_detail&amp;apid=123">detail</a></td>
      </tr>
    </table>
    """
    client = StudisClient(
        Settings(
            VUT_BASE_URL="https://www.vut.cz",
            VUT_SESSION_COOKIE="session=value",
            VUT_CACHE_DISABLED=True,
        )
    )

    async def fake_get_html(path: str) -> str:
        assert path == "/studis/student.phtml?sn=el_index"
        return html

    monkeypatch.setattr(client, "_get_html", fake_get_html)

    assert await client.get_course_detail_urls(["ABC", "MISSING"]) == {
        "ABC": "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=123"
    }

