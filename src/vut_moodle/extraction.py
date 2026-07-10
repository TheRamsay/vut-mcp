"""In-memory extraction for explicitly requested Moodle attachments."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from vut_moodle.errors import MoodleContentError
from vut_moodle.models import MoodleFile, MoodleFileContent

PDF_MIME_TYPE = "application/pdf"
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/json",
}


def extract_file_content(
    file: MoodleFile,
    data: bytes,
    content_type: str | None,
    max_characters: int,
    *,
    max_pdf_pages: int = 50,
) -> MoodleFileContent:
    """Extract bounded PDF or UTF-8 text content without persisting it."""
    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type == PDF_MIME_TYPE:
        text = _extract_pdf_text(
            data,
            max_pdf_pages=max_pdf_pages,
            max_characters=max_characters,
        )
        extractor = "pdf"
    elif normalized_content_type in TEXT_MIME_TYPES:
        text = data.decode("utf-8-sig", errors="replace")
        extractor = "text"
    else:
        raise MoodleContentError("Moodle attachment MIME type is not supported.")

    return MoodleFileContent(
        file=file,
        content_type=normalized_content_type,
        text=text[:max_characters],
        text_truncated=len(text) > max_characters,
        bytes_downloaded=len(data),
        extractor=extractor,
    )


def _normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().casefold()


def _extract_pdf_text(data: bytes, *, max_pdf_pages: int, max_characters: int) -> str:
    if not data.startswith(b"%PDF-"):
        raise MoodleContentError("Moodle attachment is not a valid PDF.")
    try:
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > max_pdf_pages:
            raise MoodleContentError(f"Moodle PDF page limit of {max_pdf_pages} exceeded.")
        text_parts: list[str] = []
        extracted_characters = 0
        extraction_limit = max_characters + 1
        for page in reader.pages:
            page_text = page.extract_text() or ""
            remaining = extraction_limit - extracted_characters
            if remaining <= 0:
                break
            text_parts.append(page_text[:remaining])
            extracted_characters += min(len(page_text), remaining)
        return "".join(text_parts)
    except MoodleContentError:
        raise
    except (PyPdfError, EOFError, IndexError, KeyError, ValueError) as error:
        raise MoodleContentError("Moodle attachment PDF could not be read.") from error
