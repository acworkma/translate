"""Durable orchestrator: Extract → Enrich → Glossary → Translate → Guardrails → Judge → (Revise loop) → Reconstruct."""
from __future__ import annotations

import logging
import os
import azure.durable_functions as df

orchestrator_bp = df.Blueprint()

PASS_THRESHOLD = float(os.environ.get("JUDGE_PASS_THRESHOLD", "4.0"))
MAX_REVISE_ATTEMPTS = int(os.environ.get("MAX_REVISE_ATTEMPTS", "2"))


@orchestrator_bp.orchestration_trigger(context_name="context")
def orchestrator(context: df.DurableOrchestrationContext):
    job = context.get_input()
    job_id = job["jobId"]
    source_blob = job["sourceBlob"]
    target_language = job["targetLanguage"]

    logging.info("orchestrator start jobId=%s lang=%s", job_id, target_language)

    # 1. Extract — Content Understanding → structured segments
    extract_result = yield context.call_activity("activity_extract", {
        "jobId": job_id,
        "sourceBlob": source_blob,
    })
    segments = extract_result["segments"]

    # 2. Enrich — Text Analytics for Health → DNT spans + entities
    segments = yield context.call_activity("activity_enrich", {
        "jobId": job_id,
        "segments": segments,
        "targetLanguage": target_language,
    })

    # 3. Glossary — pull pinned translations from Cosmos
    segments = yield context.call_activity("activity_glossary", {
        "jobId": job_id,
        "segments": segments,
        "targetLanguage": target_language,
    })

    # 4. Translate (pass 1) — GPT-4.1
    segments = yield context.call_activity("activity_translate", {
        "jobId": job_id,
        "segments": segments,
        "targetLanguage": target_language,
        "isRevision": False,
    })

    # 5. Guardrails — deterministic numeric/unit/placeholder/DNT checks
    segments = yield context.call_activity("activity_guardrails", {
        "jobId": job_id,
        "segments": segments,
    })

    # 6. Judge — Grok-3 scores quality
    judge_result = yield context.call_activity("activity_judge", {
        "jobId": job_id,
        "segments": segments,
        "targetLanguage": target_language,
        "attempt": 1,
    })

    attempt = 1
    final_judge = judge_result
    while (
        judge_result["decision"] == "REVISE"
        and judge_result["overall_score"] < PASS_THRESHOLD
        and attempt < MAX_REVISE_ATTEMPTS + 1
    ):
        attempt += 1
        logging.info("jobId=%s revising attempt=%s score=%s", job_id, attempt, judge_result["overall_score"])

        segments = yield context.call_activity("activity_revise", {
            "jobId": job_id,
            "segments": segments,
            "judgeFeedback": judge_result,
            "targetLanguage": target_language,
            "attempt": attempt,
        })

        segments = yield context.call_activity("activity_guardrails", {
            "jobId": job_id,
            "segments": segments,
        })

        judge_result = yield context.call_activity("activity_judge", {
            "jobId": job_id,
            "segments": segments,
            "targetLanguage": target_language,
            "attempt": attempt,
        })
        final_judge = judge_result

    decision = final_judge["decision"]
    score = final_judge["overall_score"]

    if decision == "REJECT" or score < PASS_THRESHOLD:
        # Route to human review — write to reviews container, do not reconstruct
        review = yield context.call_activity("activity_route_to_review", {
            "jobId": job_id,
            "segments": segments,
            "judgeResult": final_judge,
            "attempts": attempt,
        })
        return {
            "jobId": job_id,
            "status": "needs_review",
            "score": score,
            "attempts": attempt,
            "reviewBlob": review.get("reviewBlob"),
        }

    # 7. Reconstruct — write final DOCX
    final = yield context.call_activity("activity_reconstruct", {
        "jobId": job_id,
        "sourceBlob": source_blob,
        "segments": segments,
        "targetLanguage": target_language,
        "judgeResult": final_judge,
        "attempts": attempt,
    })

    return {
        "jobId": job_id,
        "status": "completed",
        "score": score,
        "attempts": attempt,
        "finalBlob": final["finalBlob"],
        "auditBlob": final["auditBlob"],
    }
