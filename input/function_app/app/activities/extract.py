"""Extract activity — calls Azure AI Content Understanding to decompose the source doc.

Content Understanding returns a structured analysis (markdown + entities + bounding
boxes + image refs). We flatten it into our `Segment` model and stash the raw
result + extracted images in the `extracted/` container for audit / reconstruction.
"""
from __future__ import annotations

import logging
import os
import time
import uuid

import azure.durable_functions as df
import httpx
from azure.identity import DefaultAzureCredential

from app.clients.blob import download_bytes, upload_bytes, upload_json
from app.models import ExtractResult, Segment

extract_bp = df.Blueprint()

CU_API_VERSION = "2025-11-01"
SCOPE = "https://cognitiveservices.azure.com/.default"


def _cu_token() -> str:
    cred = DefaultAzureCredential(
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
    )
    return cred.get_token(SCOPE).token


def _call_content_understanding(doc_bytes: bytes) -> dict:
    endpoint = os.environ["FOUNDRY_ENDPOINT"].rstrip("/")
    analyzer_id = os.environ["CONTENT_UNDERSTANDING_ANALYZER_ID"]
    url = f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyzeBinary?api-version={CU_API_VERSION}"
    headers = {
        "Authorization": f"Bearer {_cu_token()}",
        "Content-Type": "application/octet-stream",
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, content=doc_bytes)
        resp.raise_for_status()
        op_location = resp.headers.get("operation-location")
        if not op_location:
            return resp.json()

        # Poll until done
        for _ in range(60):
            time.sleep(2)
            poll = client.get(op_location, headers={"Authorization": f"Bearer {_cu_token()}"})
            poll.raise_for_status()
            body = poll.json()
            if body.get("status") in ("Succeeded", "Failed"):
                if body["status"] == "Failed":
                    raise RuntimeError(f"Content Understanding failed: {body}")
                return body.get("result") or body
        raise TimeoutError("Content Understanding polling timed out")


def _flatten_to_segments(cu_result: dict) -> tuple[list[Segment], list[str]]:
    """Convert CU result into flat Segment list. CU result shapes vary by analyzer;
    this implementation walks the most common 'contents' + 'paragraphs' + 'tables'
    layout. Adjust the analyzer schema in the Foundry portal to match these fields.
    """
    segments: list[Segment] = []
    images: list[str] = []

    contents = cu_result.get("contents") or cu_result.get("documents") or []
    if isinstance(contents, dict):
        contents = [contents]

    for doc in contents:
        for para in doc.get("paragraphs", []) or []:
            text = (para.get("content") or "").strip()
            if not text:
                continue
            kind = "heading" if para.get("role") in ("title", "sectionHeading") else "paragraph"
            segments.append(Segment(
                segment_id=para.get("id") or str(uuid.uuid4()),
                kind=kind,
                source_text=text,
            ))

        for table in doc.get("tables", []) or []:
            for cell in table.get("cells", []) or []:
                text = (cell.get("content") or "").strip()
                if not text:
                    continue
                segments.append(Segment(
                    segment_id=cell.get("id") or str(uuid.uuid4()),
                    kind="table_cell",
                    source_text=text,
                ))

        for fig in doc.get("figures", []) or []:
            ref = fig.get("id") or fig.get("imageRef")
            if ref:
                images.append(ref)

    return segments, images


@extract_bp.activity_trigger(input_name="payload")
def activity_extract(payload: dict) -> dict:
    job_id = payload["jobId"]
    source_blob = payload["sourceBlob"]  # 'inbound/<path>' or just '<path>'

    container, _, blob_path = source_blob.partition("/")
    if not blob_path:
        container, blob_path = "inbound", source_blob

    logging.info("extract jobId=%s blob=%s/%s", job_id, container, blob_path)
    doc_bytes = download_bytes(container, blob_path)

    cu_result = _call_content_understanding(doc_bytes)
    segments, images = _flatten_to_segments(cu_result)

    # Persist raw CU result + original doc copy for audit / reconstruct
    raw_path = f"{job_id}/raw.json"
    upload_json("extracted", raw_path, cu_result)

    src_copy_path = f"{job_id}/source{os.path.splitext(blob_path)[1] or '.bin'}"
    upload_bytes("extracted", src_copy_path, doc_bytes)

    result = ExtractResult(
        segments=segments,
        document_metadata={"source_blob": source_blob, "segment_count": len(segments)},
        extracted_blob_path=f"extracted/{raw_path}",
        images=images,
    )
    logging.info("extract jobId=%s segments=%d images=%d", job_id, len(segments), len(images))
    return result.model_dump()
