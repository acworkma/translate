"""Revise activity — second-pass translation, only for segments the judge flagged.

We don't re-translate the whole doc — segments with PASS-level scores are kept
to avoid introducing regressions. Reviser receives the original source, the
prior translation, the judge's feedback, and any guardrail issues.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import azure.durable_functions as df
from tenacity import retry, stop_after_attempt, wait_exponential

from app.clients.foundry import get_openai_client
from app.models import Segment

revise_bp = df.Blueprint()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
REVISER_PROMPT = (PROMPTS_DIR / "reviser.md").read_text(encoding="utf-8")

BATCH_SIZE = 15
SEGMENT_PASS_FLOOR = 4.0  # per-segment score at/above this is left alone


def _needs_revision(seg: Segment, judge_feedback: dict) -> bool:
    if seg.guardrail_issues:
        return True
    per_seg = judge_feedback.get("per_segment", {}).get(seg.segment_id)
    if not per_seg:
        return False
    score = per_seg.get("score")
    if score is None:
        return bool(per_seg.get("issues"))
    return float(score) < SEGMENT_PASS_FLOOR


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _call_reviser(batch: list[Segment], judge_feedback: dict, target_language: str) -> dict[str, str]:
    client = get_openai_client()
    payload = {
        "target_language": target_language,
        "judge_summary": judge_feedback.get("summary", ""),
        "segments": [
            {
                "segment_id": s.segment_id,
                "kind": s.kind,
                "source_text": s.source_text,
                "previous_translation": s.translated_text,
                "do_not_translate": s.dnt_terms,
                "pinned_translations": s.pinned_translations,
                "guardrail_issues": s.guardrail_issues,
                "judge_feedback": judge_feedback.get("per_segment", {}).get(s.segment_id, {}),
            }
            for s in batch
        ],
    }
    resp = client.chat.completions.create(
        model=os.environ["MODEL_TRANSLATOR"],   # same family as translator
        messages=[
            {"role": "system", "content": REVISER_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=4096,
    )
    body = json.loads(resp.choices[0].message.content)
    return {item["segment_id"]: item["translated_text"] for item in body.get("translations", [])}


@revise_bp.activity_trigger(input_name="payload")
def activity_revise(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    target_language = payload["targetLanguage"]
    judge_feedback = payload["judgeFeedback"]
    segments = [Segment(**s) for s in payload["segments"]]

    to_fix = [s for s in segments if _needs_revision(s, judge_feedback)]
    if not to_fix:
        logging.info("revise jobId=%s nothing to revise", job_id)
        return [s.model_dump() for s in segments]

    for i in range(0, len(to_fix), BATCH_SIZE):
        batch = to_fix[i:i + BATCH_SIZE]
        try:
            revised = _call_reviser(batch, judge_feedback, target_language)
        except Exception as exc:
            logging.exception("revise jobId=%s batch=%d failed: %s", job_id, i, exc)
            raise
        for s in batch:
            new_text = revised.get(s.segment_id)
            if new_text:
                s.translated_text = new_text
                s.guardrail_issues = []  # cleared; re-checked downstream

    logging.info("revise jobId=%s revised=%d/%d", job_id, len(to_fix), len(segments))
    return [s.model_dump() for s in segments]
