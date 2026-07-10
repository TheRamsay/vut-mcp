from io import BytesIO

import pytest
from pypdf import PdfWriter

from vut_moodle.errors import MoodleContentError
from vut_moodle.extraction import extract_file_content
from vut_moodle.models import MoodleFile


def _file() -> MoodleFile:
    return MoodleFile(name="attachment", url="https://moodle.vut.cz/pluginfile.php/17/file")


def _pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def test_extracts_utf8_text_and_serializes_to_json() -> None:
    result = extract_file_content(
        _file(),
        b"\xef\xbb\xbfHello Moodle",
        "text/plain; charset=utf-8",
        max_characters=20,
    )

    assert result.model_dump(mode="json") == {
        "file": {
            "name": "attachment",
            "url": "https://moodle.vut.cz/pluginfile.php/17/file",
            "size_bytes": None,
            "mimetype": None,
            "modified_at": None,
        },
        "content_type": "text/plain",
        "text": "Hello Moodle",
        "text_truncated": False,
        "bytes_downloaded": 15,
        "extractor": "text",
    }


def test_text_uses_replacement_decoding_and_reports_truncation() -> None:
    result = extract_file_content(_file(), b"abc\xffdef", "text/markdown", max_characters=4)

    assert result.text == "abc\ufffd"
    assert result.text_truncated is True


@pytest.mark.parametrize("content_type", ["text/html", "application/zip", ""])
def test_rejects_unsupported_mime_types(content_type: str) -> None:
    with pytest.raises(MoodleContentError, match="MIME type"):
        extract_file_content(_file(), b"content", content_type, max_characters=20)


def test_rejects_malformed_pdf() -> None:
    with pytest.raises(MoodleContentError, match="PDF"):
        extract_file_content(_file(), b"%PDF-not-valid", "application/pdf", max_characters=20)


def test_rejects_pdf_over_page_limit() -> None:
    with pytest.raises(MoodleContentError, match="page limit"):
        extract_file_content(
            _file(),
            _pdf(2),
            "application/pdf",
            max_characters=20,
            max_pdf_pages=1,
        )


def test_extracts_anonymous_pdf() -> None:
    result = extract_file_content(_file(), _pdf(), "application/pdf", max_characters=20)

    assert result.extractor == "pdf"
    assert result.text == ""
