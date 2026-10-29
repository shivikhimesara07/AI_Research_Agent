"""Mutation testing: plant one known bug at a time and check that the test suite catches it.

Usage (from backend/):  .venv/bin/python tools/mutate.py

Each mutant is applied to a temporary copy of app/ and tests/, so the real code is never modified.
A mutant is CAUGHT if the suite fails with it applied, SURVIVED if the suite still passes.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# (name, file, original text, mutated text)
MUTANTS = [
    ("M1 history cap 4 -> 40 exchanges", "app/services/paper_service.py",
     "HISTORY_EXCHANGES = 4", "HISTORY_EXCHANGES = 40"),
    ("M2 layout: stop skipping rotated text (arXiv stamp)", "app/services/pdf_service.py",
     "                            continue  # skip rotated", "                            pass  # skip rotated"),
    ("M3 download: ignore declared Content-Length limit", "app/services/pdf_service.py",
     "if declared > MAX_PDF_BYTES:", "if False:"),
    ("M4 LLM metadata input cap 12k -> 45k chars", "app/services/llm_service.py",
     "METADATA_INPUT_CHARS = 12_000", "METADATA_INPUT_CHARS = 45_000"),
    ("M5 LLM metadata: wrong response_schema", "app/services/llm_service.py",
     "response_schema=ExtractedMetadata,", "response_schema=dict,"),
    ("M6 upload onto saved paper: keep old PDF file", "app/services/paper_service.py",
     "                    Path(existing.pdf_path).unlink(missing_ok=True)", "                    pass"),
    ("M7 references: only skip headings in first 5%", "app/services/pdf_service.py",
     "m.start() > len(text) * 0.5", "m.start() > len(text) * 0.05"),
    ("M8 references: use FIRST heading instead of last", "app/services/pdf_service.py",
     "ref = refs[-1]", "ref = refs[0]"),
    ("M9 metadata: drop the cited-paper title guard", "app/services/paper_service.py",
     "if not found.title or _norm(found.title) not in page1_head:", "if not found.title:"),
    ("M10 year: prefer header year over arXiv stamp", "app/services/pdf_service.py",
     "        if stamp:\n            year = 2000", "        if stamp and not m:\n            year = 2000"),
    ("M11 search: fall back to arXiv on empty S2 results", "app/services/search_service.py",
     "            items = await self.s2.search(query, limit)\n",
     "            items = await self.s2.search(query, limit)\n"
     "            if not items: raise S2TransientError('empty')\n"),
    ("M12 summary cache: never regenerate abstract summaries", "app/services/paper_service.py",
     'paper.summary_basis == "full_text" or (paper.summary_basis == "abstract" and not has_full)',
     'paper.summary_basis in ("full_text", "abstract")'),
    ("M13 upload dedupe: hash filename instead of bytes", "app/services/paper_service.py",
     "file_hash = hashlib.sha256(data).hexdigest()", "file_hash = hashlib.sha256(filename.encode()).hexdigest()"),
    ("M14 S2: retry 401/403 like transient errors", "app/services/s2_client.py",
     "if resp.status_code == 429 or resp.status_code >= 500:",
     "if resp.status_code in (429, 401, 403) or resp.status_code >= 500:"),
    ("M15 download: accept HTML (drop type/magic check)", "app/services/pdf_service.py",
     'if "application/pdf" not in ctype and b"%PDF-" not in chunk[:1024]:', "if False:"),
    ("M16 abstract cap 3000 -> 300 chars", "app/services/pdf_service.py",
     "return abstract[:3000] or None", "return abstract[:300] or None"),
    ("M17 Q&A: drop 'only the paper text' instruction", "app/services/llm_service.py",
     "using only the paper text provided.", "using the paper text and your own knowledge."),
    ("M18 ask: save message even if LLM fails", "app/services/paper_service.py",
     "        answer = await self.llm.answer(paper.title, text, basis, history, question)\n"
     '        session.add(Message(paper_id=paper.id, role="user", content=question))',
     '        session.add(Message(paper_id=paper.id, role="user", content=question)); session.commit()\n'
     "        answer = await self.llm.answer(paper.title, text, basis, history, question)"),
]


def run_suite(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                          cwd=root, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for item in ("app", "tests", "pytest.ini"):
            src = BACKEND / item
            (shutil.copytree if src.is_dir() else shutil.copy)(src, root / item)

        if run_suite(root).returncode != 0:
            print("The unmutated suite fails; fix that before measuring mutants.")
            return 1

        caught = 0
        for name, rel, old, new in MUTANTS:
            path = root / rel
            original = path.read_text()
            if old not in original:
                print(f"{name:56} PATTERN NOT FOUND (code changed; update this mutant)")
                continue
            path.write_text(original.replace(old, new, 1))
            result = run_suite(root)
            path.write_text(original)
            failed = [l.split("::")[-1].split(" ")[0] for l in result.stdout.splitlines() if l.startswith("FAILED")]
            status = "CAUGHT  " if result.returncode else "SURVIVED"
            caught += bool(result.returncode)
            print(f"{name:56} {status} {failed[0] if failed else ''}")

    print(f"\nMutation score: {caught}/{len(MUTANTS)} ({100 * caught / len(MUTANTS):.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
