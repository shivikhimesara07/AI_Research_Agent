import httpx
import pytest

from app.services import pdf_service
from app.services.pdf_service import PdfService

from .pdf_factory import make_pdf


@pytest.fixture
def pdf():
    return PdfService()


# ---------- extract_text ----------


def test_extract_text_returns_full_text_and_first_two_pages(pdf, tmp_path):
    path = make_pdf(tmp_path / "p.pdf", [["page one"], ["page two"], ["page three"]])
    full, first = pdf.extract_text(path)
    assert "page one" in full and "page three" in full
    assert "page two" in first
    assert "page three" not in first


@pytest.mark.xfail(
    strict=True,
    reason="Known bug: TEXT_DEHYPHENATE doesn't join line-break hyphens in these PDFs, so full text "
    "keeps 'pre- training'. extract_abstract and layout titles work around it with a regex; "
    "extract_text does not.",
)
def test_extract_text_joins_words_hyphenated_across_lines(pdf, tmp_path):
    # "pre-" at a line end + "training" on the next line, as in the LoRA abstract.
    path = make_pdf(tmp_path / "p.pdf", [["large-scale pre-", "training on general domain data"]])
    full, _ = pdf.extract_text(path)
    assert "pretraining" in full


def test_extract_text_raises_on_corrupt_file(pdf, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7 this is not really a pdf")
    with pytest.raises(Exception):
        pdf.extract_text(bad)


# ---------- find_identifiers ----------


def test_find_identifiers_puts_arxiv_stamp_first(pdf):
    text = (
        "As shown by Devlin et al. (arXiv:1810.04805), transformers...\n"
        "arXiv:2106.09685v2 [cs.CL] 16 Oct 2021"
    )
    assert pdf.find_identifiers(text) == ["arXiv:2106.09685", "arXiv:1810.04805"]


def test_find_identifiers_handles_urls_old_style_ids_and_dois(pdf):
    text = (
        "see https://arxiv.org/abs/1706.03762v5 and arXiv:hep-th/9901001.\n"
        "DOI: 10.18653/v1/N19-1423."
    )
    assert pdf.find_identifiers(text) == [
        "arXiv:1706.03762",
        "arXiv:hep-th/9901001",
        "DOI:10.18653/v1/N19-1423",  # trailing period stripped
    ]


def test_find_identifiers_dedupes_and_strips_trailing_brackets(pdf):
    text = "(doi 10.1145/3292500.3330701) again 10.1145/3292500.3330701]"
    assert pdf.find_identifiers(text) == ["DOI:10.1145/3292500.3330701"]


def test_find_identifiers_ignores_bare_numbers(pdf):
    assert pdf.find_identifiers("Table 2106.09685 shows results in 2021.") == []


# ---------- extract_abstract ----------


def test_extract_abstract_stops_at_introduction(pdf):
    text = "Title\nAbstract\nWe study pruning.\nIt works well.\n1 Introduction\nBody text."
    assert pdf.extract_abstract(text) == "We study pruning. It works well."


def test_extract_abstract_joins_line_break_hyphens(pdf):
    text = "Abstract: Deploying indepen- dent models is costly.\nKeywords: x"
    assert pdf.extract_abstract(text) == "Deploying independent models is costly."


def test_extract_abstract_missing_returns_none(pdf):
    assert pdf.extract_abstract("Title\n1 Introduction\nNo abstract heading here.") is None


def test_extract_abstract_is_capped(pdf):
    text = "Abstract\n" + "word " * 2000 + "\nIntroduction\n"
    assert len(pdf.extract_abstract(text)) == 3000


# ---------- layout_metadata ----------


def test_layout_metadata_reads_title_authors_year_and_abstract(pdf, tmp_path):
    path = make_pdf(
        tmp_path / "p.pdf",
        [[
            ("Sparse Routing for Graph Transformers", 18),
            "Priya Raman, Tomas Lindqvist and Mei Chen",
            "Department of Computer Science, Example University",
            "Workshop on Efficient ML, 2024",
            "Abstract",
            "We introduce a sparse routing scheme.",
            "1 Introduction",
        ]],
    )
    _, first = pdf.extract_text(path)
    meta = pdf.layout_metadata(path, first)
    assert meta.title == "Sparse Routing for Graph Transformers"
    assert meta.authors == ["Priya Raman", "Tomas Lindqvist", "Mei Chen"]  # affiliation line skipped
    assert meta.year == 2024
    assert meta.abstract == "We introduce a sparse routing scheme."


def test_layout_metadata_joins_title_split_with_hyphen(pdf, tmp_path):
    # Regression (LoRA): title came out as "... LAN- GUAGE MODELS".
    path = make_pdf(
        tmp_path / "p.pdf",
        [[("LORA: LOW-RANK ADAPTATION OF LARGE LAN-", 16), ("GUAGE MODELS", 16), "Edward Hu, Yelong Shen"]],
    )
    _, first = pdf.extract_text(path)
    assert pdf.layout_metadata(path, first).title == "LORA: LOW-RANK ADAPTATION OF LARGE LANGUAGE MODELS"


def test_layout_metadata_prefers_arxiv_stamp_year_over_citation_year(pdf, tmp_path):
    # Regression (LoRA): the year regex picked 2019 from a citation instead of the arXiv id (2106 -> 2021).
    path = make_pdf(
        tmp_path / "p.pdf",
        [[("Some Paper Title", 18), "Ann Author", "Builds on Smith (2019).", "Abstract", "Text.", "Introduction"]],
        stamp="arXiv:2106.09685v2 [cs.CL] 16 Oct 2021",
    )
    _, first = pdf.extract_text(path)
    meta = pdf.layout_metadata(path, first)
    assert meta.year == 2021
    assert "arXiv" not in meta.title  # rotated stamp is not mistaken for the title


def test_layout_metadata_ignores_years_after_the_abstract(pdf, tmp_path):
    path = make_pdf(
        tmp_path / "p.pdf",
        [[("A Title Here", 18), "Ann Author", "Abstract", "Compared with work from 2019.", "Introduction"]],
    )
    _, first = pdf.extract_text(path)
    assert pdf.layout_metadata(path, first).year is None


def test_layout_metadata_falls_back_to_pdf_metadata(pdf, tmp_path):
    path = make_pdf(
        tmp_path / "p.pdf",
        [[("Only A Title", 18), "university of nowhere"]],
        metadata={"author": "Ada Lovelace; Alan Turing", "creationDate": "D:20190304120000"},
    )
    _, first = pdf.extract_text(path)
    meta = pdf.layout_metadata(path, first)
    assert meta.authors == ["Ada Lovelace", "Alan Turing"]
    assert meta.year == 2019


def test_layout_metadata_blank_page_returns_none(pdf, tmp_path):
    path = make_pdf(tmp_path / "p.pdf", [[]])
    assert pdf.layout_metadata(path, "") is None


def test_layout_metadata_corrupt_file_returns_none(pdf, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    assert pdf.layout_metadata(bad, "") is None


# ---------- strip_references ----------

BODY = "Introduction\n" + "Body sentence about the method.\n" * 40


def test_strip_references_drops_bibliography(pdf):
    text = BODY + "References\n[1] A. Smith. Some cited paper. 2019.\n"
    out = pdf.strip_references(text)
    assert "Body sentence" in out
    assert "Some cited paper" not in out


def test_strip_references_ignores_heading_in_first_half(pdf):
    text = "References\nThis early line is part of the intro.\n" + BODY
    assert pdf.strip_references(text) == text


def test_strip_references_uses_last_heading(pdf):
    text = BODY + "References\nmore body\n" + BODY + "7 REFERENCES\n[1] cited.\n"
    out = pdf.strip_references(text)
    assert "more body" in out and "[1] cited." not in out


def test_strip_references_keeps_named_appendix(pdf):
    text = BODY + "References\n[1] cited.\nAppendix A: Dataset details\n12,000 examples.\n"
    out = pdf.strip_references(text)
    assert "[1] cited." not in out
    assert "12,000 examples." in out


def test_strip_references_keeps_lettered_appendix(pdf):
    # Regression (LoRA): appendix headings are "A" on its own line, then the title.
    text = BODY + "REFERENCES\n[1] cited.\nA\nDATASET DETAILS\nWe use GLUE.\n"
    out = pdf.strip_references(text)
    assert "[1] cited." not in out
    assert "We use GLUE." in out


def test_strip_references_reference_title_starting_with_a_is_not_an_appendix(pdf):
    text = BODY + "References\nA Neural Probabilistic Language Model. Bengio et al.\n"
    assert "Neural Probabilistic" not in pdf.strip_references(text)


def test_strip_references_applies_cap(pdf):
    assert len(pdf.strip_references("x" * 500, cap=100)) == 100


# ---------- download_pdf ----------

PDF_BODY = b"%PDF-1.7\n" + b"0" * 2000


def _service(handler):
    return PdfService(transport=httpx.MockTransport(handler))


async def test_download_pdf_saves_file(tmp_path):
    svc = _service(lambda req: httpx.Response(200, content=PDF_BODY, headers={"content-type": "application/pdf"}))
    dest = tmp_path / "sub" / "p.pdf"
    assert await svc.download_pdf("https://x/p.pdf", dest) == dest
    assert dest.read_bytes() == PDF_BODY


async def test_download_pdf_accepts_octet_stream_with_magic_bytes(tmp_path):
    svc = _service(lambda req: httpx.Response(200, content=PDF_BODY, headers={"content-type": "application/octet-stream"}))
    assert await svc.download_pdf("https://x/p", tmp_path / "p.pdf") is not None


async def test_download_pdf_sends_user_agent(tmp_path):
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, content=PDF_BODY)

    await PdfService(user_agent="TestAgent/1", transport=httpx.MockTransport(handler)).download_pdf(
        "https://x", tmp_path / "p.pdf"
    )
    assert seen["ua"] == "TestAgent/1"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>publisher page</html>", headers={"content-type": "text/html"}),
        httpx.Response(404),
        httpx.Response(200, content=b"not pdf", headers={"content-type": "application/pdf"}),
        httpx.Response(200, content=PDF_BODY, headers={"content-length": str(26 * 1024 * 1024)}),
    ],
    ids=["html", "http-404", "pdf-type-but-not-pdf", "declared-too-large"],
)
async def test_download_pdf_rejects_bad_responses(tmp_path, response):
    dest = tmp_path / "p.pdf"
    assert await _service(lambda req: response).download_pdf("https://x", dest) is None
    assert not dest.exists()


async def test_download_pdf_aborts_when_stream_exceeds_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_service, "MAX_PDF_BYTES", 1000)
    svc = _service(lambda req: httpx.Response(200, content=PDF_BODY))  # 2009 bytes, no content-length check
    assert await svc.download_pdf("https://x", tmp_path / "p.pdf") is None


async def test_download_pdf_network_error_returns_none(tmp_path):
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    assert await _service(handler).download_pdf("https://x", tmp_path / "p.pdf") is None
