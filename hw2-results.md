# HW2 Results: Testing the AI Research Assistant

_Generated 2026-10-27. App code is unchanged since HW1 (commit `171a4f6`); every change below comes from the tests. Bugs found were documented as strict `xfail` tests, not fixed._

## Checkpoint comparison

| | HW1 baseline | Initial generated suite | After Round 1 | After Round 2 (final) |
|---|---|---|---|---|
| **Strategy** | Tests written during HW1 | Tests generated from the code | Tests from the requirements; copied expectations removed | Adversarial inputs against the PDF heuristics |
| **Tests** (pass + xfail) | 7 (7 + 0) | 168 (167 + 1) | 177 (174 + 3) | **225 (201 + 24)** |
| **Line coverage** | 48.1% | 97.4% | 98.5% | 98.5% |
| **Branch coverage** | 9.4% | 91.1% | 92.2% | 92.7% |
| **Combined (coverage.py)** | 41.0% | 96.3% | 97.3% | 97.4% |
| **Mutation score** (18 planted bugs) | 1/18 (6%) | 11/18 (61%) | 14/18 (78%) | 15/18 (83%) |
| **App bugs found this stage** (distinct defects) | 0 | 1 | 2 | 19 |
| **App bugs found, cumulative** | 0 | 1 | 3 | **22** |
| **Tests documenting bugs** (strict xfail) | 0 | 1 | 3 | 24 |

**Key result:** Round 2 added 48 tests and moved branch coverage by a single branch (92.2% → 92.7%), yet it found 19 of the 22 bugs. Coverage plateaued at the initial generated suite; bug discovery came from changing *what* the tests assert and *which inputs* they use, not from covering more lines.

## Test count by type

| Type | What it exercises | HW1 | Initial | Round 1 | Round 2 |
|---|---|---|---|---|---|
| Unit | One module; HTTP faked at the transport layer | 2 | 92 (91 + 1 xfail) | 93 (91 + 2 xfail) | 93 (91 + 2 xfail) |
| Service integration | `PaperService` + real in-memory DB, faked PDF/LLM/S2 | 0 | 36 | 36 | 36 |
| API | FastAPI routes with faked services | 5 | 40 | 39 | 39 |
| End-to-end (requirements) | Real PDF parser, pipeline, routes and DB; only the LLM faked | 0 | 0 | 9 (8 + 1 xfail) | 9 (8 + 1 xfail) |
| Adversarial (heuristics) | Realistic PDFs the heuristics weren't shaped for | 0 | 0 | 0 | 48 (27 + 21 xfail) |
| **Total** | | **7** | **168** | **177** | **225** |

_Round 1's API count drops by one because `test_upload_creates_paper` was rewritten as an end-to-end test._

## Final per-file coverage (vs HW1 baseline)

| File | Lines (HW1 → final) | Branches (HW1 → final) |
|---|---|---|
| `app/config.py` | 93.8% → **96.9%** | n/a → **n/a** |
| `app/db.py` | 46.3% → **100.0%** | 12.5% → **87.5%** |
| `app/deps.py` | 81.8% → **95.5%** | n/a → **n/a** |
| `app/main.py` | 96.6% → **96.6%** | 50.0% → **50.0%** |
| `app/models.py` | 100.0% → **100.0%** | n/a → **n/a** |
| `app/routers/assistant.py` | 42.1% → **100.0%** | 0.0% → **100.0%** |
| `app/routers/papers.py` | 82.5% → **100.0%** | 62.5% → **100.0%** |
| `app/routers/search.py` | 81.8% → **100.0%** | 75.0% → **75.0%** |
| `app/services/llm_service.py` | 36.2% → **98.6%** | 0.0% → **92.9%** |
| `app/services/paper_service.py` | 37.2% → **98.2%** | 16.7% → **95.8%** |
| `app/services/pdf_service.py` | 17.7% → **96.2%** | 0.0% → **89.2%** |
| `app/services/s2_client.py` | 36.8% → **100.0%** | 0.0% → **100.0%** |
| `app/services/search_service.py` | 28.4% → **100.0%** | 0.0% → **100.0%** |
| **Total** | 48.1% → **98.5%** | 9.4% → **92.7%** |

Full report with missing lines: `backend/coverage-final.txt` (baseline: `backend/coverage-baseline.txt`).

## Mutation results per planted bug

Each mutant is one deliberate bug planted in a scratch copy of the app; ✅ = the suite failed (caught).

| Mutant | HW1 | Initial | Round 1 | Round 2 |
|---|---|---|---|---|
| M1: history cap 4 -> 40 exchanges | — | ✅ | ✅ | ✅ |
| M2: layout: stop skipping rotated text (arXiv stamp) | — | — | — | ✅ |
| M3: download: ignore declared Content-Length limit | — | ✅ | ✅ | ✅ |
| M4: LLM metadata input cap 12k -> 45k chars | — | — | ✅ | ✅ |
| M5: LLM metadata: wrong response_schema | — | — | ✅ | ✅ |
| M6: upload onto saved paper: keep old PDF file | — | — | — | — |
| M7: references: only skip headings in first 5% | — | — | — | — |
| M8: references: use FIRST heading instead of last | — | — | ✅ | ✅ |
| M9: metadata: drop the cited-paper title guard | — | ✅ | ✅ | ✅ |
| M10: year: prefer header year over arXiv stamp | — | ✅ | ✅ | ✅ |
| M11: search: fall back to arXiv on empty S2 results | — | ✅ | ✅ | ✅ |
| M12: summary cache: never regenerate abstract summaries | — | ✅ | ✅ | ✅ |
| M13: upload dedupe: hash filename instead of bytes | ✅ | ✅ | ✅ | ✅ |
| M14: S2: retry 401/403 like transient errors | — | ✅ | ✅ | ✅ |
| M15: download: accept HTML (drop type/magic check) | — | — | — | — |
| M16: abstract cap 3000 -> 300 chars | — | ✅ | ✅ | ✅ |
| M17: Q&A: drop 'only the paper text' instruction | — | ✅ | ✅ | ✅ |
| M18: ask: save message even if LLM fails | — | ✅ | ✅ | ✅ |

**Still surviving (3)**, all outside what the requirements specify:
- **M6** (old PDF file not deleted when an upload attaches to a saved paper): file cleanup isn't a stated requirement; a disk-leak issue, not correctness.
- **M7** (early-heading threshold 50% → 5%): no requirement fixes a threshold; only the outcome is required.
- **M15** (early HTML check removed): effectively harmless, because the final `%PDF-` check still rejects HTML.

## App bugs found (22 distinct defects)

| # | Stage | Area | Bug |
|---|---|---|---|
| 1 | Initial | Text extraction | Words hyphenated across lines are not rejoined in the full text ("pre- training") |
| 2 | Round 1 | Authors | Names with lowercase particles are dropped ("Anna van der Berg"). Found via the API; Round 2 confirmed it at parser level |
| 3 | Round 1 | References | With two reference sections, the cut is at the last heading, so the main bibliography is sent to the LLM |
| 4 | Round 2 | Authors | Single names are dropped ("Prabhakar") |
| 5 | Round 2 | Authors | "et al." drops the whole author line |
| 6 | Round 2 | Authors | CJK names are dropped (no upper case) |
| 7 | Round 2 | Authors | Short affiliations become authors ("Meta AI", "Carnegie Mellon") |
| 8 | Round 2 | Title | A subtitle in a smaller font is dropped ("DeepRoute:") |
| 9 | Round 2 | Year | A year inside the title wins over the venue year |
| 10 | Round 2 | Year | A page range is read as the year ("pp. 1995-2010") |
| 11 | Round 2 | Year | A copyright year below the abstract is ignored |
| 12 | Round 2 | Year | Old-style arXiv stamps (`hep-th/9901001`) aren't recognised |
| 13 | Round 2 | Year + abstract | A title containing the word "Abstract" breaks both the year and the abstract |
| 14 | Round 2 | Abstract | "Summary" heading (Nature style) not recognised |
| 15 | Round 2 | Abstract | Abstract followed by "Background" instead of "Introduction" is not found |
| 16 | Round 2 | Abstract | Abstract followed by "Motivation" instead of "Introduction" is not found |
| 17 | Round 2 | Abstract | Abstract without a heading is not found (expected value is a judgment call) |
| 18 | Round 2 | References | "Literature Cited" (biology) not recognised; bibliography sent to the LLM |
| 19 | Round 2 | References | "References and Notes" (Science) not recognised |
| 20 | Round 2 | References | "References:" with a colon not recognised |
| 21 | Round 2 | References | Heading on the same line as the first entry not recognised |
| 22 | Round 2 | References | "Supplementary Information" appendix is cut off with the references |

_24 xfail tests document these 22 defects: the particle defect (#2) has a test at the API and at the parser level, and #13 has one test for the year and one for the abstract._

**Impact:** reference-stripping bugs affect *every* summary and Q&A call, because they decide what text the LLM receives. Author, title, year and abstract bugs only affect the fallback path (uploads with no arXiv ID/DOI when Gemini is unavailable).

## Method notes and caveats

- **Mutation testing:** 18 hand-written mutants, run identically at every checkpoint (`backend/tools/mutate.py`). They were chosen partly to probe suspected weak spots, so they measure *where* the suite is blind more than a random mutation rate would.
- **Correction:** the initial suite's mutation score was first reported as 12/18; the raw output shows 7 survivors, so the correct figure is **11/18**.
- **Round 1 snapshot:** reconstructed by running the final suite without `test_pdf_adversarial.py` (Round 2 added only that file and one PDF helper). It reproduces Round 1's recorded result exactly: 174 passed, 3 xfailed.
- **HW1 baseline:** coverage from `coverage-baseline.txt`; the mutation score was measured afterwards against the HW1 tests from git (`HEAD`).
- **xfail tests** document bugs and are `strict`: if a bug is fixed, the suite fails until the marker is removed.
- **Synthetic PDFs** are cleaner than real ones; real-world heuristic accuracy is likely lower than these tests show.
