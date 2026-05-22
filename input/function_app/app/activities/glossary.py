"""Glossary activity — pull pinned translations from Cosmos and attach to segments.

Cosmos `glossary` container is partitioned by /language. Each item:
  { id: "<source_term_lower>", language: "es-MX", source: "...", target: "...", notes: "..." }
"""
from __future__ import annotations

import logging

import azure.durable_functions as df

from app.clients.cosmos import get_container
from app.models import Segment

glossary_bp = df.Blueprint()


def _lookup(language: str, terms: set[str]) -> dict[str, str]:
    if not terms:
        return {}
    container = get_container("glossary")
    lowered = [t.lower() for t in terms]
    # Use IN clause; Cosmos limit is ~256 — chunk if you expect more
    placeholders = ",".join(f"@t{i}" for i in range(len(lowered)))
    query = (
        f"SELECT c.id, c.target FROM c WHERE c.language = @lang AND c.id IN ({placeholders})"
    )
    params = [{"name": "@lang", "value": language}]
    for i, t in enumerate(lowered):
        params.append({"name": f"@t{i}", "value": t})
    out = {}
    try:
        for item in container.query_items(
            query=query,
            parameters=params,
            partition_key=language,
        ):
            out[item["id"]] = item["target"]
    except Exception as exc:
        logging.warning("glossary lookup failed: %s — continuing without pins", exc)
    return out


@glossary_bp.activity_trigger(input_name="payload")
def activity_glossary(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    language = payload["targetLanguage"]
    segments = [Segment(**s) for s in payload["segments"]]

    # Collect candidate terms — DNT terms + flagged medical entity texts
    candidates: set[str] = set()
    for s in segments:
        candidates.update(s.dnt_terms)
        for e in s.medical_entities:
            if e.get("text"):
                candidates.add(e["text"])

    pins = _lookup(language, candidates)
    if pins:
        for s in segments:
            for term in list(s.dnt_terms) + [e["text"] for e in s.medical_entities if e.get("text")]:
                tgt = pins.get(term.lower())
                if tgt:
                    s.pinned_translations[term] = tgt

    logging.info("glossary jobId=%s candidates=%d pinned=%d", job_id, len(candidates), len(pins))
    return [s.model_dump() for s in segments]
