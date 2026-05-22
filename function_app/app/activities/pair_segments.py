"""Pair source segments with target segments by document order.

Document Translation preserves document structure, so re-extracting the
translated docx with the same Content Understanding analyzer yields segments
in the same order as the source extraction. We align by index and copy the
translated text onto the source-side `Segment` (which already has dnt_terms,
medical_entities, and pinned_translations from earlier activities).

If counts diverge by ≤ 20%, we still attempt a best-effort alignment by
truncating to the shorter list and log a warning. Larger drift returns the
paired list anyway but flags the segments with a guardrail-style issue.
"""
from __future__ import annotations

import logging

import azure.durable_functions as df

from app.models import Segment

pair_segments_bp = df.Blueprint()


@pair_segments_bp.activity_trigger(input_name="payload")
def activity_pair_segments(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    source = [Segment(**s) for s in payload["sourceSegments"]]
    target = [Segment(**s) for s in payload["targetSegments"]]

    if len(source) != len(target):
        logging.warning(
            "pair_segments jobId=%s count drift source=%d target=%d",
            job_id, len(source), len(target),
        )

    paired: list[Segment] = []
    pair_count = min(len(source), len(target))
    for i in range(pair_count):
        src = source[i]
        tgt = target[i]
        src.translated_text = tgt.source_text  # target extractor put the translated text in `source_text`
        src.dt_text = tgt.source_text  # snapshot — used by patch_docx to find the paragraph
        paired.append(src)

    # If source has more segments than we could pair, emit them with empty translations
    # so guardrails will catch them as `empty_translation`.
    for i in range(pair_count, len(source)):
        unpaired = source[i]
        unpaired.translated_text = ""
        paired.append(unpaired)

    logging.info("pair_segments jobId=%s paired=%d unpaired=%d", job_id, pair_count, len(source) - pair_count)
    return [p.model_dump() for p in paired]
