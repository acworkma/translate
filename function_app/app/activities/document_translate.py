"""Document Translation activity — Azure AI Translator (REST, async batch).

Submits a single-file translation job that preserves format (images, headers,
footers, tables, run-level styles) and consumes the per-job glossary TSV.

Output blob: translated/<jobId>/<lang>/<source_filename>
"""
from __future__ import annotations

import logging
import os
import time

import azure.durable_functions as df
import httpx

from app.clients.blob import blob_url, split_path
from app.clients.foundry import get_bearer_token

document_translate_bp = df.Blueprint()

TARGET_CONTAINER = os.environ.get("DOCUMENT_TRANSLATION_TARGET_CONTAINER", "translated")
API_VERSION = os.environ.get("TRANSLATOR_API_VERSION", "2024-05-01")
POLL_INTERVAL = 10  # seconds
POLL_MAX = 90        # ~15 min

# Map BCP-47 like 'es' / 'zh-Hans' to Translator service codes.
# Translator natively understands 'es', 'zh-Hans', 'vi', 'ar', 'ru'.
_LANG_MAP = {
    "es": "es",
    "zh-Hans": "zh-Hans",
    "vi": "vi",
    "ar": "ar",
    "ru": "ru",
}


def _to_translator_lang(code: str) -> str:
    return _LANG_MAP.get(code, code)


def _submit_job(source_url: str, target_url: str, target_language: str, glossary_url: str | None) -> str:
    endpoint = os.environ["TRANSLATOR_ENDPOINT"].rstrip("/")
    url = f"{endpoint}/translator/document/batches?api-version={API_VERSION}"

    target: dict = {
        "targetUrl": target_url,
        "language": _to_translator_lang(target_language),
    }
    if glossary_url:
        target["glossaries"] = [{"glossaryUrl": glossary_url, "format": "tsv"}]

    body = {
        "inputs": [
            {
                "source": {"sourceUrl": source_url, "language": "en"},
                "targets": [target],
                "storageType": "File",
            }
        ]
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {get_bearer_token()}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Document Translation submit failed: {resp.status_code} {resp.text}")
        operation_location = resp.headers.get("operation-location") or resp.headers.get("Operation-Location")
        if not operation_location:
            raise RuntimeError(f"Document Translation: missing Operation-Location header; body={resp.text}")
        return operation_location


def _poll_until_terminal(operation_location: str) -> dict:
    with httpx.Client(timeout=60.0) as client:
        for _ in range(POLL_MAX):
            time.sleep(POLL_INTERVAL)
            resp = client.get(
                operation_location,
                headers={"Authorization": f"Bearer {get_bearer_token()}"},
            )
            resp.raise_for_status()
            body = resp.json()
            status = (body.get("status") or "").lower()
            if status in ("succeeded", "failed", "validationfailed", "canceled"):
                return body
        raise TimeoutError(f"Document Translation polling timed out for {operation_location}")


@document_translate_bp.activity_trigger(input_name="payload")
def activity_document_translate(payload: dict) -> dict:
    job_id = payload["jobId"]
    source_blob = payload["sourceBlob"]
    target_language = payload["targetLanguage"]
    glossary_blob = payload.get("glossaryBlob")  # 'glossaries/<jobId>/<lang>.tsv' or None

    src_container, src_path = split_path(source_blob, default_container="inbound")
    filename = os.path.basename(src_path)
    target_blob = f"{job_id}/{target_language}/{filename}"

    source_url = blob_url(src_container, src_path)
    target_url = blob_url(TARGET_CONTAINER, target_blob)
    glossary_url = None
    if glossary_blob:
        g_container, g_path = split_path(glossary_blob, default_container="glossaries")
        glossary_url = blob_url(g_container, g_path)

    logging.info(
        "document_translate jobId=%s src=%s tgt=%s glossary=%s",
        job_id, source_url, target_url, glossary_url,
    )

    op = _submit_job(source_url, target_url, target_language, glossary_url)
    result = _poll_until_terminal(op)

    status = (result.get("status") or "").lower()
    if status != "succeeded":
        # Surface character counts and any document-level errors for diagnostics
        raise RuntimeError(f"Document Translation finished with status={status}: {result}")

    logging.info(
        "document_translate jobId=%s done characters=%s",
        job_id,
        (result.get("summary") or {}).get("totalCharacterCharged"),
    )
    return {
        "translatedBlob": f"{TARGET_CONTAINER}/{target_blob}",
        "translatedUrl": target_url,
        "summary": result.get("summary", {}),
    }
