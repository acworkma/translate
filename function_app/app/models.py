"""Pydantic models that flow between Durable activities.

Activities must return JSON-serializable values, so every model exposes
`.model_dump()` and is reconstructed on the receiving side.

Hybrid pipeline note: source-side enrichment + glossary fills the segment;
after Document Translation we re-extract the translated docx and pair it
back to the source segment by document order, populating `translated_text`.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


SegmentKind = Literal["heading", "paragraph", "list_item", "table_cell", "caption"]


class Segment(BaseModel):
    """A translatable unit extracted from the source document.

    Same model used for source-only and paired (source + translated) segments —
    `translated_text` is None on the source side and filled in by `pair_segments`.
    """
    segment_id: str
    kind: SegmentKind
    source_text: str
    # Filled in by enrich
    dnt_terms: list[str] = Field(default_factory=list)
    medical_entities: list[dict] = Field(default_factory=list)
    # Filled in by glossary
    pinned_translations: dict[str, str] = Field(default_factory=dict)
    # Filled in by pair_segments (initial) / revise (subsequent)
    translated_text: Optional[str] = None
    # The Document Translation output text for this segment — preserved across
    # revisions so `patch_docx` can locate the paragraph by text match instead
    # of by ordinal position (DI reading order ≠ python-docx body iteration).
    dt_text: Optional[str] = None
    # Filled in by guardrails
    guardrail_issues: list[str] = Field(default_factory=list)
    # Filled in by judge (per-segment)
    judge_score: Optional[float] = None
    judge_issues: list[str] = Field(default_factory=list)


class ExtractResult(BaseModel):
    segments: list[Segment]
    document_metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_blob_path: str
    images: list[str] = Field(default_factory=list)


class JudgeResult(BaseModel):
    overall_score: float
    decision: Literal["PASS", "REVISE", "REJECT"]
    per_segment: dict[str, dict] = Field(default_factory=dict)
    summary: str = ""
