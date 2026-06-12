"""Create the Content Understanding analyzer used by extract.py.

Usage (after deploy):
  CONTENT_UNDERSTANDING_ENDPOINT=https://cog-translate-cu-wus.cognitiveservices.azure.com \\
    python scripts/create_cu_analyzer.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx
from azure.identity import DefaultAzureCredential

API_VERSION = "2025-11-01"
SCOPE = "https://cognitiveservices.azure.com/.default"


def main() -> int:
    endpoint = os.environ.get("CONTENT_UNDERSTANDING_ENDPOINT")
    analyzer_id = os.environ.get("CONTENT_UNDERSTANDING_ANALYZER_ID", "translate_doc_v1")
    if not endpoint:
        print("CONTENT_UNDERSTANDING_ENDPOINT env var required", file=sys.stderr)
        return 2
    endpoint = endpoint.rstrip("/")

    cred = DefaultAzureCredential()
    token = cred.get_token(SCOPE).token

    body = {
        "description": "Document layout analyzer for medical translation pipeline",
        "baseAnalyzerId": "prebuilt-document",
        "config": {
            "enableOcr": True,
        },
        "models": {
            "completion": "gpt-4.1",
        },
    }

    url = f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}?api-version={API_VERSION}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(timeout=60.0) as client:
        resp = client.put(url, headers=headers, json=body)
        print(f"PUT {url} -> {resp.status_code}")
        if resp.status_code >= 400:
            print(resp.text)
            return 1
        op_location = resp.headers.get("operation-location") or resp.headers.get("Operation-Location")
        if op_location:
            for _ in range(60):
                time.sleep(2)
                poll = client.get(op_location, headers={"Authorization": f"Bearer {token}"})
                poll.raise_for_status()
                payload = poll.json()
                status = (payload.get("status") or "").lower()
                print(f"poll status={status}")
                if status in ("succeeded", "ready"):
                    return 0
                if status == "failed":
                    print(payload)
                    return 1
            print("analyzer creation timed out", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
