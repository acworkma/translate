"""Glossary build — emit a per-job TSV for Azure AI Translator Document Translation.

Format: tab-separated `<source>\\t<target>` lines, one pair per line. Translator
uses this as a phrase dictionary during document translation.

Writes to: glossaries/<jobId>/<lang>.tsv
"""
from __future__ import annotations

import logging
import os

import azure.durable_functions as df

from app.clients.blob import blob_url, upload_bytes
from app.models import Segment

glossary_build_bp = df.Blueprint()

GLOSSARY_CONTAINER = os.environ.get("DOCUMENT_TRANSLATION_GLOSSARY_CONTAINER", "glossaries")


@glossary_build_bp.activity_trigger(input_name="payload")
def activity_glossary_build(payload: dict) -> dict:
    job_id = payload["jobId"]
    language = payload["targetLanguage"]
    segments = [Segment(**s) for s in payload["segments"]]

    pairs: dict[str, str] = {}
    for s in segments:
        for source, target in s.pinned_translations.items():
            if source and target and source not in pairs:
                pairs[source] = target

    if not pairs:
        logging.info("glossary_build jobId=%s no pinned terms — skipping TSV", job_id)
        return {"glossaryBlob": None, "termCount": 0}

    body = "\n".join(f"{src}\t{tgt}" for src, tgt in pairs.items()).encode("utf-8")
    path = f"{job_id}/{language}.tsv"
    upload_bytes(GLOSSARY_CONTAINER, path, body, content_type="text/tab-separated-values; charset=utf-8")

    url = blob_url(GLOSSARY_CONTAINER, path)
    logging.info("glossary_build jobId=%s terms=%d blob=%s", job_id, len(pairs), url)
    return {"glossaryBlob": f"{GLOSSARY_CONTAINER}/{path}", "glossaryUrl": url, "termCount": len(pairs)}
