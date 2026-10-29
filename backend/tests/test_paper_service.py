import hashlib
from pathlib import Path

import pytest
from sqlmodel import select

from app.models import ExtractedMetadata, Message, Paper, PaperMeta
from app.services.s2_client import S2TransientError

PDF = b"%PDF-1.7 fake upload bytes"
PAGE1 = "LoRA: Low-Rank Adaptation of Large Language Models\nEdward Hu\nAbstract\n..."


def s2_item(title="LoRA: Low-Rank Adaptation of Large Language Models", authors=("Edward Hu",), **extra):
    return {"paperId": "s2-lora", "title": title, "authors": [{"name": a} for a in authors],
            "year": 2021, "abstract": "S2 abstract", "url": "https://s2/lora", **extra}


def add_paper(session, **fields) -> Paper:
    paper = Paper(**{"source": "semantic_scholar", "title": "A Paper", **fields})
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


# ---------- save / delete ----------


def test_save_meta_dedupes_by_external_id(paper_service, session):
    meta = PaperMeta(source="semantic_scholar", external_id="p1", title="T")
    first = paper_service.save_meta(session, meta)
    second = paper_service.save_meta(session, meta)
    assert first.id == second.id
    assert first.full_text is None and first.full_text_status == "pending"  # save never downloads


def test_save_meta_without_external_id_always_inserts(paper_service, session):
    meta = PaperMeta(source="arxiv", title="T")
    assert paper_service.save_meta(session, meta).id != paper_service.save_meta(session, meta).id


def test_delete_removes_paper_messages_and_pdf_file(paper_service, session, tmp_path):
    pdf_file = tmp_path / "x.pdf"
    pdf_file.write_bytes(PDF)
    paper = add_paper(session, pdf_path=str(pdf_file))
    session.add(Message(paper_id=paper.id, role="user", content="q"))
    session.commit()
    paper_service.delete(session, paper)
    assert session.exec(select(Paper)).all() == []
    assert session.exec(select(Message)).all() == []
    assert not pdf_file.exists()


# ---------- upload ----------


async def test_ingest_upload_creates_paper_with_text_and_hash(paper_service, session):
    paper, created = await paper_service.ingest_upload(session, "lora.pdf", PDF)
    assert created
    assert paper.source == "upload" and paper.title == "LLM Title"  # fake LLM stage
    assert paper.full_text_status == "ok" and paper.full_text
    assert paper.file_hash == hashlib.sha256(PDF).hexdigest()
    assert Path(paper.pdf_path).read_bytes() == PDF


async def test_ingest_upload_duplicate_skips_all_processing(paper_service, session, fake_pdf, fake_llm):
    first, _ = await paper_service.ingest_upload(session, "a.pdf", PDF)
    calls_before = (fake_pdf.extract_calls, len(fake_llm.calls))
    again, created = await paper_service.ingest_upload(session, "renamed.pdf", PDF)
    assert not created and again.id == first.id
    assert (fake_pdf.extract_calls, len(fake_llm.calls)) == calls_before


async def test_ingest_upload_with_no_extractable_text_is_marked_failed(paper_service, session, fake_pdf):
    fake_pdf.full_text = "   "
    paper, _ = await paper_service.ingest_upload(session, "scan.pdf", PDF)
    assert paper.full_text is None and paper.full_text_status == "failed"


async def test_ingest_upload_unreadable_pdf_raises_and_cleans_up(paper_service, session, fake_pdf, tmp_path):
    fake_pdf.extract_error = RuntimeError("corrupt")
    with pytest.raises(ValueError, match="Could not read PDF"):
        await paper_service.ingest_upload(session, "bad.pdf", PDF)
    assert list((tmp_path / "uploads").iterdir()) == []
    assert session.exec(select(Paper)).all() == []


async def test_ingest_upload_attaches_pdf_to_paper_saved_from_search(paper_service, session, fake_pdf, fake_s2):
    saved = add_paper(session, external_id="s2-lora", title="LoRA", full_text_status="failed")
    fake_pdf.identifiers = ["arXiv:2106.09685"]
    fake_pdf.full_text = PAGE1
    fake_s2.items["arXiv:2106.09685"] = s2_item()
    paper, created = await paper_service.ingest_upload(session, "lora.pdf", PDF)
    assert not created and paper.id == saved.id
    # The saved paper now carries the uploaded PDF and its text, with no second library entry.
    assert Path(paper.pdf_path).read_bytes() == PDF
    assert paper.full_text == PAGE1 and paper.full_text_status == "ok"
    assert len(session.exec(select(Paper)).all()) == 1


# ---------- upload metadata pipeline ----------


async def test_metadata_from_s2_lookup_when_title_is_on_page_one(paper_service, fake_pdf, fake_s2, fake_llm, tmp_path):
    fake_pdf.identifiers = ["arXiv:2106.09685"]
    fake_s2.items["arXiv:2106.09685"] = s2_item()
    meta, external_id, extra = await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert extra["stage"] == "s2_lookup" and external_id == "s2-lora"
    assert meta.authors == ["Edward Hu"] and meta.year == 2021
    assert fake_llm.calls == []  # LLM never consulted


async def test_cited_paper_id_is_rejected(paper_service, fake_pdf, fake_s2, tmp_path):
    # Page 1 mentions BERT's arXiv id, but the upload is a different paper.
    fake_pdf.identifiers = ["arXiv:1810.04805"]
    fake_s2.items["arXiv:1810.04805"] = s2_item(title="BERT: Pre-training of Deep Bidirectional Transformers")
    _, external_id, extra = await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert extra["stage"] == "llm" and external_id is None


async def test_lookup_skips_failures_and_tries_next_id(paper_service, fake_pdf, fake_s2, tmp_path):
    fake_pdf.identifiers = ["DOI:10.1/a", "arXiv:2106.09685"]
    fake_s2.items["DOI:10.1/a"] = S2TransientError("s2_rate_limited")
    fake_s2.items["arXiv:2106.09685"] = s2_item()
    _, _, extra = await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert extra["stage"] == "s2_lookup"
    assert fake_s2.lookups == ["DOI:10.1/a", "arXiv:2106.09685"]


async def test_lookup_stops_at_first_success(paper_service, fake_pdf, fake_s2, tmp_path):
    # Requirement (HW1 plan): try the stages in order, "stopping at the first success".
    fake_pdf.identifiers = ["arXiv:2106.09685", "DOI:10.1/b", "DOI:10.1/c"]
    fake_s2.items["arXiv:2106.09685"] = s2_item()
    await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert fake_s2.lookups == ["arXiv:2106.09685"]
    # Not asserted: the code also caps how many identifiers it will try when none match.
    # The requirement doesn't set a number, so the cap is the code's choice.


async def test_s2_hit_without_authors_falls_through(paper_service, fake_pdf, fake_s2, tmp_path):
    fake_pdf.identifiers = ["arXiv:2106.09685"]
    fake_s2.items["arXiv:2106.09685"] = s2_item(authors=())
    _, _, extra = await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert extra["stage"] == "llm"


async def test_missing_s2_abstract_is_filled_from_pdf(paper_service, fake_pdf, fake_s2, tmp_path):
    fake_pdf.identifiers = ["arXiv:2106.09685"]
    fake_s2.items["arXiv:2106.09685"] = s2_item(abstract=None)
    meta, _, _ = await paper_service.extract_upload_metadata(PAGE1, tmp_path / "x.pdf")
    assert meta.abstract == "Fake abstract."


async def test_llm_metadata_without_abstract_is_filled_from_pdf(paper_service, fake_llm, tmp_path):
    fake_llm.metadata_result = ExtractedMetadata(title="T", authors=["A"], abstract=None)
    meta, _, extra = await paper_service.extract_upload_metadata("text", tmp_path / "x.pdf")
    assert extra["stage"] == "llm" and meta.abstract == "Fake abstract."


@pytest.mark.parametrize(
    "result, error",
    [(None, None), (ExtractedMetadata(title="T", authors=[]), None), (None, RuntimeError("not configured"))],
    ids=["llm-none", "llm-no-authors", "llm-raises"],
)
async def test_falls_back_to_layout_when_llm_fails(paper_service, fake_llm, tmp_path, result, error):
    fake_llm.metadata_result, fake_llm.metadata_error = result, error
    meta, _, extra = await paper_service.extract_upload_metadata("text", tmp_path / "x.pdf")
    assert extra["stage"] == "layout" and meta.title == "Layout Title"


async def test_falls_back_to_filename_when_everything_fails(paper_service, fake_llm, fake_pdf, tmp_path):
    fake_llm.metadata_result = None
    fake_pdf.layout_result = None
    meta, _, extra = await paper_service.extract_upload_metadata("text", tmp_path / "x.pdf", "My Scan.pdf")
    assert extra["stage"] == "filename" and meta.title == "My Scan" and meta.authors == []


# ---------- lazy full text ----------


async def test_ensure_full_text_cached_does_nothing(paper_service, session, fake_pdf):
    paper = add_paper(session, full_text="already here", full_text_status="ok", pdf_url="https://x.pdf")
    assert await paper_service.ensure_full_text(session, paper)
    assert fake_pdf.downloads == []


async def test_ensure_full_text_downloads_open_access_pdf(paper_service, session, fake_pdf):
    fake_pdf.download_bytes = PDF
    paper = add_paper(session, pdf_url="https://oa/p.pdf")
    assert await paper_service.ensure_full_text(session, paper)
    assert fake_pdf.downloads == ["https://oa/p.pdf"]
    assert paper.full_text_status == "ok" and paper.file_hash == hashlib.sha256(PDF).hexdigest()


async def test_ensure_full_text_builds_arxiv_url_from_id(paper_service, session, fake_pdf):
    paper = add_paper(session, source="arxiv", external_id="arXiv:2106.09685")
    await paper_service.ensure_full_text(session, paper)
    assert fake_pdf.downloads == ["https://arxiv.org/pdf/2106.09685"]


async def test_ensure_full_text_uses_local_pdf_without_downloading(paper_service, session, fake_pdf, tmp_path):
    local = tmp_path / "local.pdf"
    local.write_bytes(PDF)
    paper = add_paper(session, pdf_path=str(local), pdf_url="https://oa/p.pdf")
    assert await paper_service.ensure_full_text(session, paper)
    assert fake_pdf.downloads == []


async def test_ensure_full_text_failure_is_remembered(paper_service, session, fake_pdf):
    paper = add_paper(session, pdf_url="https://publisher/landing-page")
    assert not await paper_service.ensure_full_text(session, paper)
    assert paper.full_text_status == "failed"
    assert not await paper_service.ensure_full_text(session, paper)  # no second download
    assert len(fake_pdf.downloads) == 1
    fake_pdf.download_bytes = PDF
    assert await paper_service.ensure_full_text(session, paper, retry_failed=True)
    assert len(fake_pdf.downloads) == 2


async def test_ensure_full_text_no_source_marks_failed(paper_service, session, fake_pdf):
    paper = add_paper(session, external_id="s2-only-id")
    assert not await paper_service.ensure_full_text(session, paper)
    assert fake_pdf.downloads == [] and paper.full_text_status == "failed"


# ---------- summary caching ----------


async def test_summary_is_generated_once_then_cached(paper_service, session, fake_llm):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    first = await paper_service.summarize(session, paper)
    second = await paper_service.summarize(session, paper)
    assert first == second == ("Summary of A Paper (full_text)", "full_text")
    assert [c[0] for c in fake_llm.calls] == ["summarize"]


async def test_summary_refresh_regenerates(paper_service, session, fake_llm):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    await paper_service.summarize(session, paper)
    await paper_service.summarize(session, paper, refresh=True)
    assert len(fake_llm.calls) == 2


async def test_summary_falls_back_to_abstract(paper_service, session):
    paper = add_paper(session, abstract="Only the abstract.")
    assert await paper_service.summarize(session, paper) == ("Summary of A Paper (abstract)", "abstract")


async def test_abstract_summary_is_regenerated_when_full_text_appears(paper_service, session, fake_pdf, fake_llm):
    paper = add_paper(session, abstract="abs", pdf_url="https://oa/p.pdf")
    _, basis = await paper_service.summarize(session, paper)
    assert basis == "abstract"
    fake_pdf.download_bytes = PDF  # the PDF becomes reachable
    _, basis = await paper_service.summarize(session, paper, refresh=True)
    assert basis == "full_text"


async def test_cached_abstract_summary_regenerated_without_refresh_once_text_exists(paper_service, session, fake_llm):
    # e.g. the user uploads the PDF for a paper whose summary was built from the abstract.
    paper = add_paper(session, summary="old abstract summary", summary_basis="abstract",
                      full_text="now we have the body", full_text_status="ok")
    summary, basis = await paper_service.summarize(session, paper)
    assert basis == "full_text" and summary != "old abstract summary"
    assert len(fake_llm.calls) == 1


async def test_cached_abstract_summary_kept_while_full_text_unavailable(paper_service, session, fake_llm):
    paper = add_paper(session, abstract="abs")
    await paper_service.summarize(session, paper)
    await paper_service.summarize(session, paper)
    assert len(fake_llm.calls) == 1


async def test_llm_input_without_abstract_uses_placeholder(paper_service, session, fake_llm):
    paper = add_paper(session)
    await paper_service.summarize(session, paper)
    text, basis = paper_service._llm_input(paper)
    assert basis == "abstract" and "No abstract" in text


# ---------- Q&A ----------


async def test_ask_persists_question_and_answer(paper_service, session):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    answer, basis = await paper_service.ask(session, paper, "What datasets?")
    assert (answer, basis) == ("Answer to: What datasets?", "full_text")
    assert [(m.role, m.content) for m in paper_service.messages(session, paper.id)] == [
        ("user", "What datasets?"), ("assistant", "Answer to: What datasets?")]


async def test_ask_sends_only_recent_history(paper_service, session, fake_llm):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    for i in range(6):
        await paper_service.ask(session, paper, f"Q{i}")
    history = fake_llm.calls[-1][2]
    # Requirement (HW1 plan): send only the last 3-4 exchanges, not the whole thread.
    sent_questions = [content for role, content in history if role == "user"]
    assert 3 <= len(sent_questions) <= 4
    assert sent_questions[-1] == "Q4"                      # the most recent exchange is included
    assert "Q0" not in sent_questions                      # the oldest one is dropped
    assert history[-1] == ("assistant", "Answer to: Q4")
    assert len(paper_service.messages(session, paper.id)) == 12  # full history still stored


async def test_ask_history_always_starts_with_a_user_turn(paper_service, session, fake_llm):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    session.add(Message(paper_id=paper.id, role="assistant", content="orphan"))
    session.commit()
    await paper_service.ask(session, paper, "Q")
    assert fake_llm.calls[-1][2] == []


async def test_failed_answer_is_not_persisted(paper_service, session, fake_llm):
    paper = add_paper(session, full_text="body", full_text_status="ok")
    fake_llm.error = RuntimeError("LLM down")
    with pytest.raises(RuntimeError):
        await paper_service.ask(session, paper, "Q")
    assert paper_service.messages(session, paper.id) == []
