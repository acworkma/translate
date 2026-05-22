"""Blob client for the document storage account. Entra-only auth."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from azure.storage.blob import BlobServiceClient, ContentSettings

from .foundry import get_credential


@lru_cache(maxsize=1)
def get_blob_service() -> BlobServiceClient:
    return BlobServiceClient(
        account_url=os.environ["DOCUMENT_STORAGE_BLOB_ENDPOINT"],
        credential=get_credential(),
    )


def split_path(path: str, default_container: str = "inbound") -> tuple[str, str]:
    """Split 'container/path/to/file' or 'path/to/file' into (container, blob_path)."""
    container, _, rest = path.partition("/")
    if not rest:
        return default_container, path
    return container, rest


def download_bytes(container: str, blob_path: str) -> bytes:
    return get_blob_service().get_blob_client(container, blob_path).download_blob().readall()


def upload_bytes(container: str, blob_path: str, data: bytes, content_type: Optional[str] = None) -> str:
    bc = get_blob_service().get_blob_client(container, blob_path)
    kwargs = {}
    if content_type:
        kwargs["content_settings"] = ContentSettings(content_type=content_type)
    bc.upload_blob(data, overwrite=True, **kwargs)
    return f"{container}/{blob_path}"


def upload_json(container: str, blob_path: str, payload) -> str:
    return upload_bytes(
        container,
        blob_path,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )


def blob_url(container: str, blob_path: str) -> str:
    """Full https URL — used by Document Translation as source/target/glossary URLs."""
    base = os.environ["DOCUMENT_STORAGE_BLOB_ENDPOINT"].rstrip("/")
    return f"{base}/{container}/{blob_path}"
