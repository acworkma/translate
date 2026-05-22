"""Entry point — registers HTTP starter, orchestrator, and all activity functions."""
import logging
import azure.functions as func
import azure.durable_functions as df

from app.orchestrator import orchestrator_bp
from app.activities.extract import extract_bp
from app.activities.enrich import enrich_bp
from app.activities.glossary import glossary_bp
from app.activities.translate import translate_bp
from app.activities.guardrails import guardrails_bp
from app.activities.judge import judge_bp
from app.activities.revise import revise_bp
from app.activities.reconstruct import reconstruct_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

app.register_blueprint(orchestrator_bp)
app.register_blueprint(extract_bp)
app.register_blueprint(enrich_bp)
app.register_blueprint(glossary_bp)
app.register_blueprint(translate_bp)
app.register_blueprint(guardrails_bp)
app.register_blueprint(judge_bp)
app.register_blueprint(revise_bp)
app.register_blueprint(reconstruct_bp)


@app.route(route="jobs", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_job(req: func.HttpRequest, client) -> func.HttpResponse:
    """POST /api/jobs — start a translation job.

    Body: { "jobId": "...", "sourceBlob": "inbound/<path>", "targetLanguage": "es-MX" }
    """
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse("invalid json body", status_code=400)

    for field in ("jobId", "sourceBlob", "targetLanguage"):
        if not payload.get(field):
            return func.HttpResponse(f"missing field: {field}", status_code=400)

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
    return func.HttpResponse(status.to_json_string(), mimetype="application/json")
