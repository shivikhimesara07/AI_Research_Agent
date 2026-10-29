"""Adversarial inputs for the PDF heuristics (Round 2).

Each case is something a real paper plausibly contains but earlier tests avoided because it
doesn't fit the parser's shape. Expected values are what the field SHOULD be. Where the heuristic
gets it wrong, the case is xfail(strict=True) and documented as a bug; the app is not changed.
"""
import pytest

from app.services.pdf_service import PdfService

from .pdf_factory import make_layout_pdf, make_pdf

pdf = PdfService()


def bug(reason):
    return pytest.mark.xfail(strict=True, reason=f"BUG: {reason}")


def metadata_for(tmp_path, page1, **kwargs):
    path = make_pdf(tmp_path / "p.pdf", [page1], **kwargs)
    _, first = pdf.extract_text(path)
    return pdf.layout_metadata(path, first)


def paper_with_authors(author_lines):
    return [("Graph Methods for Crop Yield Prediction", 18), *author_lines,
            "Abstract", "We predict yields.", "1 Introduction"]


# ======================================================================================
# Author parsing
# ======================================================================================

AUTHOR_CASES = [
    pytest.param(["Jean-Pierre Dupont, Marie-Claire Laurent"], ["Jean-Pierre Dupont", "Marie-Claire Laurent"],
                 id="hyphenated-names"),
    pytest.param(["J. R. R. Tolkien and C. S. Lewis"], ["J. R. R. Tolkien", "C. S. Lewis"], id="initials"),
    pytest.param(["José Müller, Zoë Ørsted and Björn Ångström"], ["José Müller", "Zoë Ørsted", "Björn Ångström"],
                 id="non-ascii-latin"),
    pytest.param(["Alice Smith1,2, Bob Jones3 and Carol White1"], ["Alice Smith", "Bob Jones", "Carol White"],
                 id="affiliation-superscripts"),
    pytest.param(["Alice Smith", "Massachusetts Institute of Technology", "Bob Jones", "Stanford University"],
                 ["Alice Smith", "Bob Jones"], id="one-author-per-line-with-affiliations"),
    pytest.param(["Anna van der Berg and Luis de la Cruz"], ["Anna van der Berg", "Luis de la Cruz"],
                 id="name-particles", marks=bug("lowercase particles fail the capitalised-words check; got [] (both authors lost)")),
    pytest.param(["Prabhakar and Alice Smith"], ["Prabhakar", "Alice Smith"], id="single-name", marks=bug("one-word names are discarded; got ['Alice Smith']")),
    pytest.param(["Alice Smith et al."], ["Alice Smith"], id="et-al", marks=bug("'et al.' makes the whole name fail the check; got [] instead of ['Alice Smith']")),
    pytest.param(["Alice Smith", "Meta AI", "Bob Jones", "Carnegie Mellon"], ["Alice Smith", "Bob Jones"],
                 id="short-affiliations-that-look-like-names", marks=bug("two capitalised words pass as a name; got ['Alice Smith', 'Meta AI', 'Bob Jones', 'Carnegie Mellon']")),
    pytest.param(["Alexandra Konstantinopoulou-Papadimitriou and Bob Lee"],
                 ["Alexandra Konstantinopoulou-Papadimitriou", "Bob Lee"], id="long-double-surname"),
]


@pytest.mark.parametrize("author_lines, expected", AUTHOR_CASES)
def test_authors(tmp_path, author_lines, expected):
    assert metadata_for(tmp_path, paper_with_authors(author_lines)).authors == expected


@bug("CJK characters have no upper case, so the capitalised-words check drops them; got []")
def test_authors_in_cjk_script(tmp_path):
    path = make_layout_pdf(tmp_path / "p.pdf", [[
        {"text": "Graph Methods for Crop Yield Prediction", "size": 18},
        {"text": "张伟, 李娜", "font": "china-s"},
        {"text": "Abstract"}, {"text": "We predict yields."}, {"text": "1 Introduction"},
    ]])
    _, first = pdf.extract_text(path)
    assert pdf.layout_metadata(path, first).authors == ["张伟", "李娜"]


# ======================================================================================
# Title detection
# ======================================================================================


def test_title_spanning_three_lines(tmp_path):
    meta = metadata_for(tmp_path, [("Sparse Mixture Routing for", 18), ("Efficient Graph Transformers", 18),
                                   ("on Molecular Benchmarks", 18), "Alice Smith", "Abstract", "x", "Introduction"])
    assert meta.title == "Sparse Mixture Routing for Efficient Graph Transformers on Molecular Benchmarks"


def test_title_in_all_caps(tmp_path):
    meta = metadata_for(tmp_path, [("ATTENTION IS ALL YOU NEED", 18), "Alice Smith", "Abstract", "x", "Introduction"])
    assert meta.title == "ATTENTION IS ALL YOU NEED"


def test_title_with_subtitle_on_same_size_line(tmp_path):
    meta = metadata_for(tmp_path, [("DeepRoute:", 18), ("Learning to Route Packets", 18), "Alice Smith",
                                   "Abstract", "x", "Introduction"])
    assert meta.title == "DeepRoute: Learning to Route Packets"


@bug("only lines at the largest font size form the title; got 'DeepRoute:'")
def test_title_with_subtitle_in_smaller_font(tmp_path):
    meta = metadata_for(tmp_path, [("DeepRoute:", 20), ("Learning to Route Packets with Graph Networks", 15),
                                   "Alice Smith", "Abstract", "x", "Introduction"])
    assert meta.title == "DeepRoute: Learning to Route Packets with Graph Networks"


def test_title_with_footnote_marker(tmp_path):
    path = make_layout_pdf(tmp_path / "p.pdf", [[
        {"text": "Sparse Routing for Graph Transformers", "size": 18, "y": 90, "advance": False},
        {"text": "*", "size": 9, "x": 400, "y": 82},
        {"text": "Alice Smith", "y": 120}, {"text": "Abstract"}, {"text": "x"}, {"text": "Introduction"},
    ]])
    _, first = pdf.extract_text(path)
    assert pdf.layout_metadata(path, first).title == "Sparse Routing for Graph Transformers"


def test_arxiv_stamp_in_larger_font_than_title(tmp_path):
    # Real arXiv stamps are large grey vertical text in the margin, often bigger than the title.
    path = make_layout_pdf(tmp_path / "p.pdf", [[
        {"text": "Sparse Routing for Graph Transformers", "size": 16},
        {"text": "Alice Smith"}, {"text": "Abstract"}, {"text": "We route."}, {"text": "1 Introduction"},
        {"text": "arXiv:2106.09685v2 [cs.LG] 16 Oct 2021", "size": 24, "x": 40, "y": 620, "rotate": 90},
    ]])
    _, first = pdf.extract_text(path)
    meta = pdf.layout_metadata(path, first)
    assert meta.title == "Sparse Routing for Graph Transformers"
    assert meta.authors == ["Alice Smith"]


def test_title_below_a_large_conference_banner(tmp_path):
    meta = metadata_for(tmp_path, [("Published as a conference paper at ICLR 2024", 9),
                                   ("Sparse Routing for Graph Transformers", 17), "Alice Smith",
                                   "Abstract", "x", "Introduction"])
    assert meta.title == "Sparse Routing for Graph Transformers"


# ======================================================================================
# Year extraction (the paper's publication year)
# ======================================================================================

YEAR_CASES = [
    pytest.param([("Lessons from the 2020 Pandemic for Epidemic Models", 18), "Alice Smith",
                  "KDD Conference 2023", "Abstract", "x", "Introduction"], 2023, id="year-inside-title", marks=bug("first year in the header wins, and the title is in the header; got 2020")),
    pytest.param([("Graph Routing", 18), "Alice Smith", "Journal of Networks, Vol. 12, pp. 1995-2010, 2021",
                  "Abstract", "x", "Introduction"], 2021, id="page-range-looks-like-a-year", marks=bug("a page number in the range 1980-2039 is read as a year; got 1995")),
    pytest.param([("Graph Routing", 18), "Alice Smith", "Abstract", "We route packets.", "Introduction",
                  "(c) 2023 Association for Computing Machinery."], 2023, id="copyright-line-below-abstract", marks=bug("years after the Abstract heading are ignored; got None")),
    pytest.param([("Graph Routing", 18), "Alice Smith", "Abstract", "x", "Introduction",
                  "arXiv:hep-th/9901001v2 [hep-th] 5 Jan 1999"], 1999, id="old-style-arxiv-stamp", marks=bug("only new-style arXiv ids (YYMM.NNNNN) are recognised as stamps; got None")),
    pytest.param([("Graph Routing", 18), "Alice Smith", "Proceedings of ACL 2019", "Abstract",
                  "We extend Smith (2017).", "Introduction"], 2019, id="plain-venue-year"),
]


@pytest.mark.parametrize("page1, expected", YEAR_CASES)
def test_year(tmp_path, page1, expected):
    assert metadata_for(tmp_path, page1).year == expected


@bug("the header is cut at the first word 'Abstract', which is in the title; year None, abstract starts 'Syntax Trees...'")
def test_title_containing_the_word_abstract(tmp_path):
    meta = metadata_for(tmp_path, [("Abstract Syntax Trees for Code Search", 18), "Alice Smith",
                                   "ICSE 2022", "Abstract", "We search code with ASTs.", "1 Introduction"])
    assert meta.year == 2022
    assert meta.abstract == "We search code with ASTs."


# ======================================================================================
# Abstract detection
# ======================================================================================

ABSTRACT_CASES = [
    pytest.param("Title\nAuthors\nSummary\nWe study pruning in protein models.\nIntroduction\nBody.",
                 "We study pruning in protein models.", id="summary-heading", marks=bug("only 'Abstract' is recognised as the heading; got None")),
    pytest.param("Title\nAuthors\nAbstract—We study pruning in protein models.\nIndex Terms—pruning\nBody.",
                 "We study pruning in protein models.", id="ieee-inline-dash"),
    pytest.param("Title\nAuthors\nABSTRACT\nWe study pruning in protein models.\n1. INTRODUCTION\nBody.",
                 "We study pruning in protein models.", id="all-caps"),
    pytest.param("Title\nAuthors\nAbstract\nWe study pruning in protein models.\n1 Background\nBody.",
                 "We study pruning in protein models.", id="followed-by-background-not-introduction", marks=bug("the abstract must be followed by Introduction/Keywords/Index Terms/CCS Concepts; got None")),
    pytest.param("Title\nAuthors\nAbstract\nWe study pruning in protein models.\n1 Motivation\nBody.",
                 "We study pruning in protein models.", id="followed-by-motivation", marks=bug("the abstract must be followed by Introduction/Keywords/Index Terms/CCS Concepts; got None")),
    pytest.param("Abstract Syntax Trees for Search\nAuthors\nAbstract\nWe search code.\n1 Introduction\nBody.",
                 "We search code.", id="title-contains-word-abstract", marks=bug("the first occurrence of 'abstract' anywhere is used; got 'Syntax Trees for Search Authors ...'")),
    pytest.param("Title\nAuthors\nWe study pruning in protein models.\n1 Introduction\nBody.",
                 "We study pruning in protein models.", id="no-abstract-heading", marks=bug("an abstract without a heading is never found; got None. (What counts as the abstract here is a judgment call.)")),
]


@pytest.mark.parametrize("text, expected", ABSTRACT_CASES)
def test_abstract(text, expected):
    assert pdf.extract_abstract(text) == expected


def test_two_column_paper_abstract_and_metadata(tmp_path):
    # LaTeX-style two-column page: full-width title and authors, then the left column, then the right.
    left = [{"text": t, "x": 50, "size": 9} for t in [
        "Abstract", "We study how attention heads in pro-", "tein language models can be pruned",
        "without losing accuracy.", "1 Introduction", "Protein language models are slow."]]
    right = [{"text": t, "x": 320, "size": 9} for t in [
        "trade-offs remain. Our contributions are", "three-fold, as listed below.", "2 Related Work"]]
    right[0]["y"] = 150
    path = make_layout_pdf(tmp_path / "p.pdf", [[
        {"text": "Tidal Attention Pruning", "size": 18, "y": 80},
        {"text": "Ingrid Halvorsen and Chidi Okafor", "y": 110},
        {**left[0], "y": 150}, *left[1:], *right]])
    _, first = pdf.extract_text(path)
    meta = pdf.layout_metadata(path, first)
    assert meta.title == "Tidal Attention Pruning"
    assert meta.authors == ["Ingrid Halvorsen", "Chidi Okafor"]
    assert meta.abstract == "We study how attention heads in protein language models can be pruned without losing accuracy."


# ======================================================================================
# Reference stripping
# ======================================================================================

BODY = "Introduction\n" + "Body sentence about the method.\n" * 40

REFERENCE_HEADINGS = [
    pytest.param("References", id="references"),
    pytest.param("Bibliography", id="bibliography"),
    pytest.param("Works Cited", id="works-cited"),
    pytest.param("REFERENCES", id="all-caps"),
    pytest.param("8 References", id="numbered"),
    pytest.param("VII. REFERENCES", id="roman-numbered"),
    pytest.param("References:", id="trailing-colon", marks=bug("'References:' with a colon is not recognised; bibliography kept")),
    pytest.param("Literature Cited", id="literature-cited-biology", marks=bug("'Literature Cited' is not recognised; bibliography kept")),
    pytest.param("References and Notes", id="references-and-notes-science", marks=bug("'References and Notes' is not recognised; bibliography kept")),
]


@pytest.mark.parametrize("heading", REFERENCE_HEADINGS)
def test_reference_section_is_dropped(heading):
    out = pdf.strip_references(BODY + f"{heading}\n[1] A. Smith. A cited paper. 2019.\n")
    assert "Body sentence" in out
    assert "A cited paper" not in out


@bug("the heading must be alone on its line; bibliography kept")
def test_reference_heading_on_same_line_as_first_entry():
    # Some PDFs extract the heading and the first reference as one line.
    out = pdf.strip_references(BODY + "References [1] A. Smith. A cited paper. 2019.\n[2] B. Jones. Another.\n")
    assert "A cited paper" not in out and "Another." not in out


APPENDIX_HEADINGS = [
    pytest.param("Appendix A: Hyperparameters", id="appendix-a"),
    pytest.param("A\nHYPERPARAMETERS", id="lettered-own-line"),
    pytest.param("Supplementary Material", id="supplementary-material"),
    pytest.param("Supplementary Information", id="supplementary-information-nature", marks=bug("'Supplementary Information' is not recognised as an appendix; the appendix is dropped with the references")),
    pytest.param("Appendices", id="appendices"),
    pytest.param("A. HYPERPARAMETERS AND SETUP", id="lettered-same-line"),
]


@pytest.mark.parametrize("heading", APPENDIX_HEADINGS)
def test_appendix_after_references_is_kept(heading):
    out = pdf.strip_references(BODY + f"References\n[1] cited.\n{heading}\nLearning rate 3e-4 for all runs.\n")
    assert "[1] cited." not in out
    assert "Learning rate 3e-4" in out
