"""Extract activity — calls Azure AI Content Understanding to decompose a DOCX
into reading-order paragraphs (incl. table-cell paragraphs).

Used twice per job: once on the English source (mode=source) and again on the
Document Translation output (mode=target). Both runs produce a flat list of
`Segment` records in the same reading order so `pair_segments` can align them.

Content Understanding is not yet in eastus2 — the workload runs in eastus2 but
a dedicated Content Understanding Cognitive Services account is deployed in a
CU-supported region (westus). Its endpoint is supplied via the
`CONTENT_UNDERSTANDING_ENDPOINT` app setting.
"""
from __future__ import annotations

import logging
import os
import time

import azure.durable_functions as df
import httpx

from app.clients.blob import download_bytes, split_path, upload_bytes, upload_json
from app.clients.foundry import get_bearer_token
from app.models import ExtractResult, Segment

extract_bp = df.Blueprint()

CU_API_VERSION = "2025-11-01"
SKIP_ROLES = {"pageHeader", "pageFooter", "pageNumber"}


def _call_content_understanding(doc_bytes: bytes) -> dict:
    endpoint = os.environ["CONTENT_UNDERSTANDING_ENDPOINT"].rstrip("/")
    analyzer_id = os.environ["CONTENT_UNDERSTANDING_ANALYZER_ID"]
    url = f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyzeBinary?api-version={CU_API_VERSION}"

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {get_bearer_token()}",
                "Content-Type": "application/octet-stream",
            },
            content=doc_bytes,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Content Understanding submit failed: {resp.status_code} {resp.text}")
        op_location = resp.headers.get("operation-location") or resp.headers.get("Operation-Location")
        if not op_location:
            return resp.json().get("result") or resp.json()

        for _ in range(60):
            time.sleep(2)
            poll = client.get(op_location, headers={"Authorization": f"Bearer {get_bearer_token()}"})
            poll.raise_for_status()
            body = poll.json()
            status = (body.get("status") or "").lower()
            if status == "succeeded":
                return body.get("result") or body
            if status == "failed":
                raise RuntimeError(f"Content Understanding failed: {body}")
        raise TimeoutError("Content Understanding polling timed out")


def _flatten_to_segments(cu_result: dict) -> tuple[list[Segment], list[str]]:
    segments: list[Segment] = []
    images: list[str] = []

    contents = cu_result.get("contents") or cu_result.get("documents") or []
    if isinstance(contents, dict):
        contents = [contents]
    if not contents and "paragraphs" in cu_result:
        contents = [cu_result]

    for doc in contents:
        for para in doc.get("paragraphs", []) or []:
            text = (para.get("content") or "").strip()
            if not text:
                continue
            role = para.get("role")
            if role in SKIP_ROLES:
                continue
            kind = "heading" if role in ("title", "sectionHeading") else "paragraph"
            segments.append(Segment(
                segment_id=f"p-{len(segments):05d}",
                kind=kind,
                source_text=text,
            ))

        for fig in doc.get("figures", []) or []:
            ref = fig.get("id") or str(fig.get("boundingRegions") or "")
            if ref:
                images.append(ref)

    return segments, images


@extract_bp.activity_trigger(input_name="payload")
def activity_extract(payload: dict) -> dict:
    job_id = payload["jobId"]
    blob_path = payload["blobPath"]
    mode = payload.get("mode", "source")

    container, path = split_path(blob_path, default_container="inbound")
    logging.info("extract jobId=%s mode=%s blob=%s/%s", job_id, mode, container, path)

    doc_bytes = download_bytes(container, path)
    cu_result = _call_content_understanding(doc_bytes)
    segments, images = _flatten_to_segments(cu_result)

    raw_path = f"{job_id}/{mode}-raw.json"
    upload_json("extracted", raw_path, cu_result)

    if mode == "source":
        ext = os.path.splitext(path)[1] or ".bin"
        upload_bytes("extracted", f"{job_id}/source{ext}", doc_bytes)

    result = ExtractResult(
        segments=segments,
        document_metadata={"blob_path": blob_path, "segment_count": len(segments), "mode": mode},
        extracted_blob_path=f"extracted/{raw_path}",
        images=images,
    )
    logging.info("extract jobId=%s mode=%s segments=%d images=%d", job_id, mode, len(segments), len(images))
    return result.model_dump()
