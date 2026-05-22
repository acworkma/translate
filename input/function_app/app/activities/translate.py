"""Translate activity — pass 1 translation via GPT-4.1.

Sends segments in small batches and asks the model to return JSON keyed by
segment_id. Pinned glossary terms and DNT spans are passed verbatim so the
model uses them.
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

translate_bp = df.Blueprint()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
TRANSLATOR_PROMPT = (PROMPTS_DIR / "translator.md").read_text(encoding="utf-8")

BATCH_SIZE = 20


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _call_translator(batch: list[Segment], target_language: str) -> dict[str, str]:
    client = get_openai_client()
    payload = {
        "target_language": target_language,
        "segments": [
            {
                "segment_id": s.segment_id,
                "kind": s.kind,
                "source_text": s.source_text,
                "do_not_translate": s.dnt_terms,
                "pinned_translations": s.pinned_translations,
                "medical_entities": [
                    {"text": e["text"], "category": e.get("category")} for e in s.medical_entities
                ],
            }
            for s in batch
        ],
    }
    resp = client.chat.completions.create(
        model=os.environ["MODEL_TRANSLATOR"],
        messages=[
            {"role": "system", "content": TRANSLATOR_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=4096,
    )
    body = json.loads(resp.choices[0].message.content)
    return {item["segment_id"]: item["translated_text"] for item in body.get("translations", [])}


@translate_bp.activity_trigger(input_name="payload")
def activity_translate(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    target_language = payload["targetLanguage"]
    segments = [Segment(**s) for s in payload["segments"]]

    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        try:
            translations = _call_translator(batch, target_language)
        except Exception as exc:
            logging.exception("translate jobId=%s batch=%d failed: %s", job_id, i, exc)
            raise
        for s in batch:
            s.translated_text = translations.get(s.segment_id, s.translated_text or "")

    logging.info("translate jobId=%s segments=%d", job_id, len(segments))
    return [s.model_dump() for s in segments]
