"""Pydantic models that flow between Durable activities.

Activities must return JSON-serializable values, so every model exposes
`.model_dump()` and is reconstructed on the receiving side.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class Segment(BaseModel):
    """A translatable unit extracted from the source document.

    `segment_id` is stable across the whole pipeline so the reviser and
    reconstructor can match output back to source.
    """
    segment_id: str
    kind: Literal["heading", "paragraph", "list_item", "table_cell", "caption"]
    source_text: str
    # Filled in by enrich
    dnt_terms: list[str] = Field(default_factory=list)        # do-not-translate spans
    medical_entities: list[dict] = Field(default_factory=list)
    # Filled in by glossary
    pinned_translations: dict[str, str] = Field(default_factory=dict)
    # Filled in by translate / revise
    translated_text: Optional[str] = None
    # Filled in by guardrails
    guardrail_issues: list[str] = Field(default_factory=list)
    # Filled in by judge (per-segment)
    judge_score: Optional[float] = None
    judge_issues: list[str] = Field(default_factory=list)


class ExtractResult(BaseModel):
    segments: list[Segment]
    document_metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_blob_path: str          # extracted/<jobId>/raw.json
    images: list[str] = Field(default_factory=list)  # blob paths of preserved images


class JudgeResult(BaseModel):
    overall_score: float
    decision: Literal["PASS", "REVISE", "REJECT"]
    per_segment: dict[str, dict] = Field(default_factory=dict)  # segment_id -> {score, issues}
    summary: str = ""


class JobState(BaseModel):
    job_id: str
    source_blob: str
    target_language: str
    attempt: int = 0
    status: Literal[
        "extracting",
        "enriching",
        "translating",
        "judging",
        "revising",
        "reconstructing",
        "needs_review",
        "completed",
        "failed",
    ] = "extracting"
    final_blob: Optional[str] = None
    audit_blob: Optional[str] = None
    last_score: Optional[float] = None
    error: Optional[str] = None
