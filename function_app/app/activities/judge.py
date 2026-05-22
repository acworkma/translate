"""Judge activity — LLM scores translation quality across paired segments."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import azure.durable_functions as df
from tenacity import retry, stop_after_attempt, wait_exponential

from app.clients.foundry import get_openai_client
from app.models import JudgeResult, Segment

judge_bp = df.Blueprint()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
JUDGE_PROMPT = (PROMPTS_DIR / "judge.md").read_text(encoding="utf-8")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _call_judge(segments: list[Segment], target_language: str, attempt: int) -> dict:
    client = get_openai_client()
    payload = {
        "target_language": target_language,
        "attempt": attempt,
        "segments": [
            {
                "segment_id": s.segment_id,
                "kind": s.kind,
                "source_text": s.source_text,
                "translated_text": s.translated_text,
                "do_not_translate": s.dnt_terms,
                "pinned_translations": s.pinned_translations,
                "medical_entities": [
                    {"text": e["text"], "category": e.get("category")} for e in s.medical_entities
                ],
                "guardrail_issues": s.guardrail_issues,
            }
            for s in segments
        ],
    }
    resp = client.chat.completions.create(
        model=os.environ["MODEL_JUDGE"],
        messages=[
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=4096,
    )
    return json.loads(resp.choices[0].message.content)


@judge_bp.activity_trigger(input_name="payload")
def activity_judge(payload: dict) -> dict:
    job_id = payload["jobId"]
    target_language = payload["targetLanguage"]
    attempt = payload.get("attempt", 1)
    segments = [Segment(**s) for s in payload["segments"]]

    raw = _call_judge(segments, target_language, attempt)

    per_segment = raw.get("per_segment", [])
    per_segment_map: dict[str, dict] = {}
    if isinstance(per_segment, list):
        for item in per_segment:
            sid = item.get("segment_id")
            if sid:
                per_segment_map[sid] = {
                    "score": item.get("score"),
                    "issues": item.get("issues", []),
                }
    elif isinstance(per_segment, dict):
        per_segment_map = per_segment

    result = JudgeResult(
        overall_score=float(raw.get("overall_score", 0.0)),
        decision=raw.get("decision", "REVISE"),
        per_segment=per_segment_map,
        summary=raw.get("summary", ""),
    )

    logging.info(
        "judge jobId=%s attempt=%d score=%.2f decision=%s",
        job_id, attempt, result.overall_score, result.decision,
    )
    return result.model_dump()
