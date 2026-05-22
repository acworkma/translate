"""Guardrails — deterministic checks that don't trust the LLM.

For each translated segment we verify:
  - numbers in source appear in translation
  - units (mg, mL, kg, mcg, IU, %, etc.) appear unchanged
  - placeholders ({patient_name}, [DOB], <<...>>) are preserved
  - DNT terms appear verbatim in translation

Failures populate `segment.guardrail_issues` — the judge sees these and the
reviser is required to fix them.
"""
from __future__ import annotations

import logging
import re

import azure.durable_functions as df

from app.models import Segment

guardrails_bp = df.Blueprint()

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
UNIT_RE = re.compile(
    r"\b(?:mg|mcg|ug|µg|g|kg|lb|oz|mL|ml|L|IU|U|cc|tsp|tbsp|gtt|mEq|mmol|mosm|"
    r"%|bpm|mmHg|cm|mm|in|°F|°C|hr|min|sec|h)\b",
    re.IGNORECASE,
)
PLACEHOLDER_RES = [
    re.compile(r"\{[^{}]+\}"),
    re.compile(r"<<[^<>]+>>"),
    re.compile(r"\[[A-Z_][A-Z0-9_\- ]{2,}\]"),
]


def _multiset(values):
    """Return a frozen multiset (Counter) of stripped strings."""
    from collections import Counter
    return Counter(v.strip() for v in values if v.strip())


def _check_one(seg: Segment) -> list[str]:
    issues: list[str] = []
    src = seg.source_text or ""
    tgt = seg.translated_text or ""

    if not tgt.strip():
        return ["empty_translation"]

    # Numbers
    src_nums = _multiset(NUMBER_RE.findall(src))
    tgt_nums = _multiset(NUMBER_RE.findall(tgt))
    missing_nums = src_nums - tgt_nums
    extra_nums = tgt_nums - src_nums
    if missing_nums:
        issues.append(f"missing_numbers:{sorted(missing_nums.elements())}")
    if extra_nums:
        issues.append(f"extra_numbers:{sorted(extra_nums.elements())}")

    # Units
    src_units = _multiset(UNIT_RE.findall(src))
    tgt_units = _multiset(UNIT_RE.findall(tgt))
    missing_units = src_units - tgt_units
    if missing_units:
        issues.append(f"missing_units:{sorted(missing_units.elements())}")

    # Placeholders
    for rx in PLACEHOLDER_RES:
        src_phs = _multiset(rx.findall(src))
        tgt_phs = _multiset(rx.findall(tgt))
        if src_phs != tgt_phs:
            missing = src_phs - tgt_phs
            if missing:
                issues.append(f"missing_placeholders:{sorted(missing.elements())}")

    # DNT terms — must appear verbatim
    for term in seg.dnt_terms:
        # Allow pinned translation override
        pinned = seg.pinned_translations.get(term)
        if pinned:
            if pinned not in tgt:
                issues.append(f"missing_pinned:{term}->{pinned}")
        else:
            if term not in tgt:
                issues.append(f"missing_dnt:{term}")

    return issues


@guardrails_bp.activity_trigger(input_name="payload")
def activity_guardrails(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    segments = [Segment(**s) for s in payload["segments"]]
    total = 0
    for s in segments:
        s.guardrail_issues = _check_one(s)
        if s.guardrail_issues:
            total += 1
    logging.info("guardrails jobId=%s segments_with_issues=%d/%d", job_id, total, len(segments))
    return [s.model_dump() for s in segments]
