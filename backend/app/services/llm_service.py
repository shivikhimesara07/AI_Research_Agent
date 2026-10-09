"""LLM access. Everything else depends on the LLMService protocol, never on Gemini directly."""
import asyncio
import logging
from typing import Protocol

from pydantic import ValidationError

from ..models import ExtractedMetadata

log = logging.getLogger(__name__)

METADATA_INPUT_CHARS = 12_000


class LLMError(Exception):
    pass


class LLMNotConfigured(LLMError):
    pass


class LLMRateLimited(LLMError):
    pass


class LLMService(Protocol):
    async def summarize(self, title: str, text: str, basis: str) -> str: ...

    async def answer(
        self, title: str, text: str, basis: str, history: list[tuple[str, str]], question: str
    ) -> str: ...

    async def extract_metadata(self, first_pages_text: str) -> ExtractedMetadata | None: ...


SUMMARY_PROMPT = """Summarize the research paper below for a researcher deciding whether to read it.
Use Markdown with these sections:
**Problem** – what problem it addresses and why it matters.
**Approach** – the core idea / method.
**Experiments** – datasets, baselines, and key quantitative results.
**Contributions** – the main contributions.
**Limitations** – stated or evident limitations.
Be specific: cite numbers, dataset names, and method names from the text. Do not invent details.
Start directly with the **Problem** section: no preamble, title line, or horizontal rules.
{basis_note}

Title: {title}

--- PAPER TEXT ---
{text}"""

QA_SYSTEM = """You answer questions about one research paper, using only the paper text provided.
If the text does not contain the answer, say so plainly instead of guessing.
Be concise and specific; quote short phrases or numbers from the paper when useful.
{basis_note}

Title: {title}

--- PAPER TEXT ---
{text}"""

ABSTRACT_NOTE = (
    "NOTE: Only the abstract is available for this paper (the full text could not be retrieved). "
    "Make that limitation clear where it matters."
)

METADATA_PROMPT = """Extract bibliographic metadata from the first pages of this research paper.
Return the paper's own title, the full list of author names (people only, no affiliations or emails),
the publication year if stated, and the abstract text verbatim. Use null for anything not present.

--- FIRST PAGES ---
{text}"""


class GeminiLLMService:
    def __init__(self, api_key: str | None, model: str, *, max_attempts: int = 2):
        self.model = model
        self.max_attempts = max_attempts
        self._client = None
        if api_key:
            from google import genai

            self._client = genai.Client(api_key=api_key)

    def _require_client(self):
        if self._client is None:
            raise LLMNotConfigured(
                "GEMINI_API_KEY is not set. Add it to .env and restart the backend."
            )
        return self._client

    async def _generate(self, contents, config=None):
        from google.genai import errors

        client = self._require_client()
        for attempt in range(self.max_attempts):
            try:
                return await client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as exc:
                if exc.code == 429:
                    if attempt + 1 < self.max_attempts:
                        await asyncio.sleep(5 * (attempt + 1))
                        continue
                    raise LLMRateLimited("Gemini rate limit hit; try again in a minute") from exc
                if exc.code in (400, 401, 403) and "api key" in (exc.message or "").lower():
                    raise LLMNotConfigured(
                        "GEMINI_API_KEY was rejected by Google. Check the key in .env and restart the backend."
                    ) from exc
                raise LLMError(f"Gemini error {exc.code}: {exc.message}") from exc
        raise LLMRateLimited("Gemini rate limit hit; try again in a minute")

    async def summarize(self, title: str, text: str, basis: str) -> str:
        prompt = SUMMARY_PROMPT.format(
            title=title, text=text, basis_note=ABSTRACT_NOTE if basis == "abstract" else ""
        )
        resp = await self._generate(prompt)
        return (resp.text or "").strip()

    async def answer(
        self, title: str, text: str, basis: str, history: list[tuple[str, str]], question: str
    ) -> str:
        from google.genai import types

        contents = [
            types.Content(role="user" if role == "user" else "model", parts=[types.Part(text=content)])
            for role, content in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        config = types.GenerateContentConfig(
            system_instruction=QA_SYSTEM.format(
                title=title, text=text, basis_note=ABSTRACT_NOTE if basis == "abstract" else ""
            )
        )
        resp = await self._generate(contents, config)
        return (resp.text or "").strip()

    async def extract_metadata(self, first_pages_text: str) -> ExtractedMetadata | None:
        """Structured extraction. Returns None on any failure so the caller falls through."""
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedMetadata,
            temperature=0,
        )
        try:
            resp = await self._generate(
                METADATA_PROMPT.format(text=first_pages_text[:METADATA_INPUT_CHARS]), config
            )
            meta = ExtractedMetadata.model_validate_json(resp.text or "")
        except (LLMError, ValidationError, ValueError) as exc:
            log.info("Gemini metadata extraction failed: %s", exc)
            return None
        if not meta.title.strip():
            return None
        return meta
