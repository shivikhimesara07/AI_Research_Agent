"""SQLModel tables and API request/response schemas."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import JSON, Column, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

Source = Literal["semantic_scholar", "arxiv", "upload"]
ContentBasis = Literal["full_text", "abstract"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- tables ----------


class Paper(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source: str
    external_id: str | None = Field(default=None, unique=True, index=True)
    title: str
    authors: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    year: int | None = None
    abstract: str | None = Field(default=None, sa_column=Column(Text))
    url: str | None = None
    pdf_url: str | None = None
    pdf_path: str | None = None
    full_text: str | None = Field(default=None, sa_column=Column(Text))
    full_text_status: str = "pending"  # pending | ok | failed
    summary: str | None = Field(default=None, sa_column=Column(Text))
    summary_basis: str | None = None  # full_text | abstract
    created_at: datetime = Field(default_factory=_now)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(
        sa_column=Column(Integer, ForeignKey("paper.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    role: str  # user | assistant
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=_now)


# ---------- schemas ----------


class PaperMeta(BaseModel):
    """Paper metadata as returned by search, and as posted to save a result."""

    source: Source
    external_id: str | None = None
    title: str
    authors: list[str] = []
    year: int | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_url: str | None = None


class SearchResult(PaperMeta):
    saved_id: int | None = None


class SearchResponse(BaseModel):
    source: Literal["semantic_scholar", "arxiv"]
    fallback_reason: str | None = None
    results: list[SearchResult]


class PaperOut(BaseModel):
    id: int
    source: str
    external_id: str | None
    title: str
    authors: list[str]
    year: int | None
    abstract: str | None
    url: str | None
    pdf_url: str | None
    has_pdf: bool
    full_text_status: str
    summary: str | None
    summary_basis: str | None
    created_at: datetime

    @classmethod
    def from_paper(cls, p: Paper) -> "PaperOut":
        return cls(
            id=p.id,
            source=p.source,
            external_id=p.external_id,
            title=p.title,
            authors=p.authors or [],
            year=p.year,
            abstract=p.abstract,
            url=p.url,
            pdf_url=p.pdf_url,
            has_pdf=bool(p.pdf_path),
            full_text_status=p.full_text_status,
            summary=p.summary,
            summary_basis=p.summary_basis,
            created_at=p.created_at,
        )


class SummaryResponse(BaseModel):
    summary: str
    summary_basis: ContentBasis


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    content_basis: ContentBasis


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ExtractedMetadata(BaseModel):
    """Schema the LLM must fill when extracting metadata from an uploaded PDF."""

    title: str
    authors: list[str]
    year: int | None = None
    abstract: str | None = None
