"""Route to review — produce a human-review bundle when the judge rejects."""
from __future__ import annotations

import logging

import azure.durable_functions as df

from app.clients.blob import upload_json
from app.models import Segment

route_to_review_bp = df.Blueprint()


@route_to_review_bp.activity_trigger(input_name="payload")
def activity_route_to_review(payload: dict) -> dict:
    job_id = payload["jobId"]
    target_language = payload["targetLanguage"]
    segments = [Segment(**s) for s in payload["segments"]]

    bundle = {
        "jobId": job_id,
        "targetLanguage": target_language,
        "translatedBlob": payload.get("translatedBlob"),
        "attempts": payload.get("attempts"),
        "judgeResult": payload.get("judgeResult"),
        "segments": [s.model_dump() for s in segments],
    }
    review_path = f"{job_id}/review.json"
    upload_json("reviewed", review_path, bundle)
    logging.info("route_to_review jobId=%s segments=%d", job_id, len(segments))
    return {"reviewBlob": f"reviewed/{review_path}"}
