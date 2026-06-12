"""FastAPI demo for the translation pipeline.

Endpoints:
  GET  /                     -> redirect to /login or /app
  GET  /login                -> login form
  POST /login                -> auth (password)
  POST /logout
  GET  /app                  -> single-page UI (requires session)
  POST /api/jobs             -> upload + start orchestration
  GET  /api/jobs/{jobId}     -> step state + score + outputs
  GET  /api/jobs/{jobId}/download -> stream final or review file
"""
from __future__ import annotations

import io
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

import httpx
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from docx import Document
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("demo")

# ---------- config ----------
PASSWORD = os.environ.get("DEMO_PASSWORD", "fr24")
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)
FUNCTION_HOST = os.environ.get("FUNCTION_HOST", "").rstrip("/")
FUNCTION_KEY_SECRET_URI = os.environ.get("FUNCTION_KEY_SECRET_URI", "")
FUNCTION_KEY_INLINE = os.environ.get("FUNCTION_KEY", "")  # optional fallback
STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT_NAME", "")
SUPPORTED_LANGUAGES = [
    s.strip() for s in os.environ.get("SUPPORTED_LANGUAGES", "es,sw,so,my,ar").split(",") if s.strip()
]
LANG_LABELS = {
    "es": "Spanish",
    "sw": "Swahili",
    "so": "Somali",
    "my": "Burmese",
    "ar": "Arabic",
    "zh-Hans": "Simplified Chinese",
    "vi": "Vietnamese",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
}

# Ordered pipeline steps surfaced in the UI.
STEPS: List[Dict[str, str]] = [
    {"key": "extract_source", "label": "Extract source (Content Understanding)", "activity": "activity_extract"},
    {"key": "enrich", "label": "Enrich (TA4Health)", "activity": "activity_enrich"},
    {"key": "glossary_lookup", "label": "Glossary lookup (Cosmos DB)", "activity": "activity_glossary_lookup"},
    {"key": "glossary_build", "label": "Build glossary (Blob)", "activity": "activity_glossary_build"},
    {"key": "document_translate", "label": "Document Translation (AI Translator)", "activity": "activity_document_translate"},
    {"key": "extract_target", "label": "Extract target (Content Understanding)", "activity": "activity_extract"},  # 2nd call
    {"key": "pair", "label": "Pair segments (in-proc)", "activity": "activity_pair_segments"},
    {"key": "guardrails", "label": "Guardrails (in-proc)", "activity": "activity_guardrails"},
    {"key": "judge", "label": "Judge (Foundry)", "activity": "activity_judge"},
    {"key": "finalize", "label": "Finalize / route (Blob)", "activity": "activity_patch_docx"},  # or route_to_review
]

# ---------- azure clients (lazy) ----------
_credential: Optional[DefaultAzureCredential] = None
_blob: Optional[BlobServiceClient] = None
_function_key_cache: Dict[str, Any] = {"value": "", "fetched_at": 0.0}


def credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        client_id = os.environ.get("AZURE_CLIENT_ID")
        if client_id:
            _credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        else:
            _credential = DefaultAzureCredential()
    return _credential


def blob_client() -> BlobServiceClient:
    global _blob
    if _blob is None:
        if not STORAGE_ACCOUNT:
            raise RuntimeError("STORAGE_ACCOUNT_NAME not configured")
        _blob = BlobServiceClient(
            account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
            credential=credential(),
        )
    return _blob


def function_key() -> str:
    """Resolve the function key — from Key Vault, env, or cache (5 min)."""
    now = time.time()
    if _function_key_cache["value"] and now - _function_key_cache["fetched_at"] < 300:
        return _function_key_cache["value"]
    val = FUNCTION_KEY_INLINE
    if not val and FUNCTION_KEY_SECRET_URI:
        # URI: https://<vault>.vault.azure.net/secrets/<name>[/<version>]
        # split -> ['https:', '', '<vault>...', 'secrets', '<name>', '<version>?']
        parts = FUNCTION_KEY_SECRET_URI.rstrip("/").split("/")
        vault_url = "/".join(parts[:3])
        secret_name = parts[4] if len(parts) > 4 else None
        version = parts[5] if len(parts) > 5 else None
        if not secret_name:
            raise RuntimeError(f"could not parse FUNCTION_KEY_SECRET_URI: {FUNCTION_KEY_SECRET_URI}")
        client = SecretClient(vault_url=vault_url, credential=credential())
        secret = client.get_secret(secret_name, version=version) if version else client.get_secret(secret_name)
        val = secret.value or ""
    if not val:
        raise RuntimeError("function key unavailable; set FUNCTION_KEY or FUNCTION_KEY_SECRET_URI")
    _function_key_cache["value"] = val
    _function_key_cache["fetched_at"] = now
    return val


# ---------- session ----------
serializer = URLSafeSerializer(SESSION_SECRET, salt="demo-session")
COOKIE_NAME = "demo_session"


def make_cookie(payload: Dict[str, Any]) -> str:
    return serializer.dumps(payload)


def read_cookie(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        return serializer.loads(token)
    except BadSignature:
        return None


def require_session(demo_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    sess = read_cookie(demo_session)
    if not sess or not sess.get("authed"):
        raise HTTPException(status_code=401, detail="login required")
    return sess


# ---------- app ----------
app = FastAPI(title="Translate Demo")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def root(demo_session: Optional[str] = Cookie(default=None)) -> Response:
    sess = read_cookie(demo_session)
    if sess and sess.get("authed"):
        return RedirectResponse("/app", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: Optional[str] = None) -> HTMLResponse:
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@app.post("/login")
def login(password: str = Form(...)) -> Response:
    if password != PASSWORD:
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        make_cookie({"authed": True, "ts": int(time.time())}),
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60 * 8,
    )
    return resp


@app.post("/logout")
def logout() -> Response:
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request, sess: Dict[str, Any] = Depends(require_session)) -> HTMLResponse:
    languages = [{"code": c, "label": LANG_LABELS.get(c, c)} for c in SUPPORTED_LANGUAGES]
    return templates.TemplateResponse(
        "app.html",
        {
            "request": request,
            "languages": languages,
            "steps": STEPS,
            "function_host": FUNCTION_HOST,
            "storage_account": STORAGE_ACCOUNT,
        },
    )


# ---------- pipeline API ----------
def _job_id(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename or "doc"))[0]
    base = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in base).strip("-") or "doc"
    return f"demo-{base[:30]}-{int(time.time())}"


@app.post("/api/jobs")
async def start_job(
    file: UploadFile = File(...),
    language: str = Form(...),
    sess: Dict[str, Any] = Depends(require_session),
) -> JSONResponse:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"unsupported language; allowed: {SUPPORTED_LANGUAGES}")
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "only .docx files are supported")

    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")

    job_id = _job_id(file.filename)
    blob_name = f"{job_id}/source.docx"

    # 1) upload to inbound
    bc = blob_client().get_blob_client(container="inbound", blob=blob_name)
    bc.upload_blob(
        data,
        overwrite=True,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # 2) kick off orchestration
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{FUNCTION_HOST}/api/jobs",
            params={"code": function_key()},
            json={
                "jobId": job_id,
                "sourceBlob": f"inbound/{blob_name}",
                "targetLanguage": language,
            },
        )
        if r.status_code != 202:
            log.error("function start failed: %s %s", r.status_code, r.text[:500])
            raise HTTPException(502, f"function start failed: HTTP {r.status_code}")

    log.info("started jobId=%s lang=%s file=%s bytes=%d", job_id, language, file.filename, len(data))
    return JSONResponse({"jobId": job_id, "language": language, "fileName": file.filename})


def _derive_step(history: List[Dict[str, Any]], runtime_status: str) -> Dict[str, Any]:
    """Derive current pipeline step from orchestration history."""
    # Count activity invocations to disambiguate two extract calls.
    extract_count = 0
    completed: List[str] = []
    in_progress: Optional[str] = None

    by_event = {}
    for ev in history:
        name = ev.get("Name") or ev.get("FunctionName") or ""
        et = ev.get("EventType")
        if et == "TaskScheduled":
            by_event.setdefault(ev.get("EventId"), name)

    # Walk history in order; track started vs completed per activity occurrence.
    activity_occurrences: List[Dict[str, Any]] = []  # {name, started, completed}
    open_idx_by_eventid: Dict[int, int] = {}

    for ev in history:
        et = ev.get("EventType")
        if et == "TaskScheduled":
            name = ev.get("Name", "")
            activity_occurrences.append({"name": name, "started": True, "completed": False})
            open_idx_by_eventid[ev.get("EventId")] = len(activity_occurrences) - 1
        elif et in ("TaskCompleted", "TaskFailed"):
            sched_id = ev.get("TaskScheduledId")
            idx = open_idx_by_eventid.get(sched_id)
            if idx is not None:
                activity_occurrences[idx]["completed"] = True

    # Map occurrences -> step keys
    extract_seen = 0
    step_state: Dict[str, str] = {s["key"]: "pending" for s in STEPS}
    last_in_progress: Optional[str] = None

    activity_to_step: Dict[str, str] = {}
    for s in STEPS:
        if s["activity"] != "activity_extract":
            activity_to_step[s["activity"]] = s["key"]

    # patch_docx OR route_to_review both map to finalize
    activity_to_step["activity_route_to_review"] = "finalize"

    for occ in activity_occurrences:
        name = occ["name"]
        if name == "activity_extract":
            key = "extract_source" if extract_seen == 0 else "extract_target"
            extract_seen += 1
        else:
            key = activity_to_step.get(name)
        if not key:
            continue
        if occ["completed"]:
            step_state[key] = "done"
            last_in_progress = None
        else:
            step_state[key] = "running"
            last_in_progress = key

    if runtime_status == "Completed":
        for k in step_state:
            step_state[k] = "done"
        last_in_progress = None
    elif runtime_status in ("Failed", "Terminated"):
        if last_in_progress:
            step_state[last_in_progress] = "failed"

    return {"steps": step_state, "currentStep": last_in_progress}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, sess: Dict[str, Any] = Depends(require_session)) -> JSONResponse:
    if not job_id.startswith("demo-"):
        raise HTTPException(400, "bad job id")
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(
            f"{FUNCTION_HOST}/api/jobs/{job_id}",
            params={"code": function_key()},
        )
        if r.status_code == 404:
            raise HTTPException(404, "job not found")
        if r.status_code >= 400:
            raise HTTPException(502, f"status fetch failed: HTTP {r.status_code}")
        primary = r.json()

        # also fetch history (durable webhook) for step derivation
        history: List[Dict[str, Any]] = []
        # use the management API via host admin? not exposed. We instead use the master-key durable webhook from the function host metadata.
        # Simpler: query the standard webhook with the connection name; but we don't have the durable-task code key. So derive from custom_status alternative — fall back to runtime_status only.
        # Since we can't get history without the durable webhook code, we use a heuristic: while Running, show "running" on whatever step the runtime is on based on elapsed time.
        runtime_status = primary.get("runtimeStatus", "")

    output = primary.get("output") or {}
    state = {"steps": {s["key"]: "pending" for s in STEPS}, "currentStep": None}

    if runtime_status == "Completed":
        for s in STEPS:
            state["steps"][s["key"]] = "done"
    elif runtime_status in ("Failed", "Terminated"):
        state["currentStep"] = None
    else:
        # Heuristic time-based progression while Running.
        created = primary.get("createdTime")
        elapsed = 0
        if created:
            try:
                from datetime import datetime, timezone
                t0 = datetime.fromisoformat(created.replace("Z", "+00:00"))
                elapsed = max(0, int((datetime.now(timezone.utc) - t0).total_seconds()))
            except Exception:
                elapsed = 0
        # rough per-step seconds budget based on observed ~80s run
        budgets = [4, 4, 3, 2, 35, 10, 2, 2, 12, 6]  # sum ~80s
        cumulative = 0
        current = None
        for i, s in enumerate(STEPS):
            cumulative += budgets[i]
            if elapsed < cumulative:
                current = s["key"]
                state["steps"][s["key"]] = "running"
                for j in range(i):
                    state["steps"][STEPS[j]["key"]] = "done"
                break
        if current is None:
            # exceeded budget — show last as running
            current = STEPS[-1]["key"]
            for s in STEPS[:-1]:
                state["steps"][s["key"]] = "done"
            state["steps"][current] = "running"
        state["currentStep"] = current

    return JSONResponse({
        "jobId": job_id,
        "runtimeStatus": runtime_status,
        "output": output,
        "steps": state["steps"],
        "currentStep": state["currentStep"],
    })


@app.get("/api/jobs/{job_id}/preview/{language}")
async def get_preview_with_lang(
    job_id: str,
    language: str,
    sess: Dict[str, Any] = Depends(require_session),
) -> JSONResponse:
    if not job_id.startswith("demo-"):
        raise HTTPException(400, "bad job id")

    src_bc = blob_client().get_blob_client(container="inbound", blob=f"{job_id}/source.docx")
    src_paragraphs: List[str] = []
    try:
        src_paragraphs = _docx_paragraphs(src_bc.download_blob().readall())
    except Exception:
        pass

    tgt_paragraphs: List[str] = []
    for container, blob_name in (
        ("final", f"{job_id}/{language}/source.docx"),
        ("translated", f"{job_id}/{language}/source.docx"),
    ):
        try:
            b = blob_client().get_blob_client(container=container, blob=blob_name)
            tgt_paragraphs = _docx_paragraphs(b.download_blob().readall())
            break
        except Exception:
            continue

    return JSONResponse({"source": src_paragraphs[:30], "target": tgt_paragraphs[:30]})


def _docx_paragraphs(data: bytes) -> List[str]:
    doc = Document(io.BytesIO(data))
    return [p.text for p in doc.paragraphs if p.text and p.text.strip()]


@app.get("/api/jobs/{job_id}/download")
async def download(
    job_id: str,
    language: str,
    sess: Dict[str, Any] = Depends(require_session),
) -> StreamingResponse:
    if not job_id.startswith("demo-"):
        raise HTTPException(400, "bad job id")
    last_err: Optional[Exception] = None
    for container, ext in (("final", "docx"), ("translated", "docx")):
        try:
            bc = blob_client().get_blob_client(container=container, blob=f"{job_id}/{language}/source.{ext}")
            data = bc.download_blob().readall()
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="{job_id}-{language}.docx"'},
            )
        except Exception as exc:
            last_err = exc
            continue
    raise HTTPException(404, f"no translated file: {last_err}")


@app.get("/api/jobs/{job_id}/review")
async def download_review(
    job_id: str,
    sess: Dict[str, Any] = Depends(require_session),
) -> StreamingResponse:
    if not job_id.startswith("demo-"):
        raise HTTPException(400, "bad job id")
    bc = blob_client().get_blob_client(container="reviewed", blob=f"{job_id}/review.json")
    data = bc.download_blob().readall()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-review.json"'},
    )
