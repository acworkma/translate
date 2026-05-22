"""Entry point — registers HTTP starter, orchestrator, and all activity functions."""
import json
import logging
import os
import azure.functions as func
import azure.durable_functions as df

from app.orchestrator import orchestrator_bp
from app.activities.extract import extract_bp
from app.activities.enrich import enrich_bp
from app.activities.glossary_lookup import glossary_lookup_bp
from app.activities.glossary_build import glossary_build_bp
from app.activities.document_translate import document_translate_bp
from app.activities.pair_segments import pair_segments_bp
from app.activities.guardrails import guardrails_bp
from app.activities.judge import judge_bp
from app.activities.revise import revise_bp
from app.activities.patch_docx import patch_docx_bp
from app.activities.route_to_review import route_to_review_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

for bp in (
    orchestrator_bp,
    extract_bp,
    enrich_bp,
    glossary_lookup_bp,
    glossary_build_bp,
    document_translate_bp,
    pair_segments_bp,
    guardrails_bp,
    judge_bp,
    revise_bp,
    patch_docx_bp,
    route_to_review_bp,
):
    app.register_blueprint(bp)


def _supported_languages() -> set[str]:
    raw = os.environ.get("SUPPORTED_LANGUAGES", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


@app.route(route="jobs", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_job(req: func.HttpRequest, client) -> func.HttpResponse:
    """POST /api/jobs — start a translation job.

    Body: { "jobId": "...", "sourceBlob": "inbound/<path>", "targetLanguage": "es" }
    """
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse("invalid json body", status_code=400)

    for field in ("jobId", "sourceBlob", "targetLanguage"):
        if not payload.get(field):
            return func.HttpResponse(f"missing field: {field}", status_code=400)

    supported = _supported_languages()
    if supported and payload["targetLanguage"] not in supported:
        return func.HttpResponse(
            f"unsupported targetLanguage; supported: {sorted(supported)}",
            status_code=400,
        )

    instance_id = await client.start_new("orchestrator", payload["jobId"], payload)
    logging.info("started orchestration jobId=%s instanceId=%s", payload["jobId"], instance_id)
    return client.create_check_status_response(req, instance_id)


@app.route(route="jobs/{jobId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_status(req: func.HttpRequest, client) -> func.HttpResponse:
    """GET /api/jobs/{jobId} — return orchestration status."""
    job_id = req.route_params.get("jobId")
    status = await client.get_status(job_id, show_input=False, show_output=True)
    if status is None:
        return func.HttpResponse("not found", status_code=404)
    body = {
        "instanceId": status.instance_id,
        "runtimeStatus": str(status.runtime_status).rsplit(".", 1)[-1],
        "output": status.output,
        "customStatus": status.custom_status,
        "createdTime": status.created_time.isoformat() if status.created_time else None,
        "lastUpdatedTime": status.last_updated_time.isoformat() if status.last_updated_time else None,
    }
    return func.HttpResponse(json.dumps(body, default=str), mimetype="application/json")
