"""Blob client for the document storage account."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from azure.storage.blob import BlobServiceClient

from .foundry import get_credential


@lru_cache(maxsize=1)
def get_blob_service() -> BlobServiceClient:
    return BlobServiceClient(
        account_url=os.environ["DOCUMENT_STORAGE_BLOB_ENDPOINT"],
        credential=get_credential(),
    )


def download_bytes(container: str, blob_path: str) -> bytes:
    svc = get_blob_service()
    return svc.get_blob_client(container, blob_path).download_blob().readall()


def download_text(container: str, blob_path: str, encoding: str = "utf-8") -> str:
    return download_bytes(container, blob_path).decode(encoding)


def upload_bytes(container: str, blob_path: str, data: bytes, content_type: Optional[str] = None) -> str:
    svc = get_blob_service()
    bc = svc.get_blob_client(container, blob_path)
    extra = {}
    if content_type:
        from azure.storage.blob import ContentSettings
        extra["content_settings"] = ContentSettings(content_type=content_type)
    bc.upload_blob(data, overwrite=True, **extra)
    return f"{container}/{blob_path}"


def upload_json(container: str, blob_path: str, payload) -> str:
    return upload_bytes(
        container,
        blob_path,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )
