"""Durable orchestrator — hybrid flow.

Source extract → enrich → glossary lookup → glossary TSV build
    → Document Translation (format-preserving spine)
    → re-extract translated docx
    → pair source ↔ target segments
    → guardrails → judge
    → (revise loop on flagged segments only)
    → patch translated docx for revised segments → final/<jobId>/<lang>/source.docx
    → audit bundle
"""
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

    # 1. Extract source — Content Understanding
    source_extract = yield context.call_activity("activity_extract", {
        "jobId": job_id,
        "blobPath": source_blob,
        "mode": "source",
    })
    source_segments = source_extract["segments"]

    # 2. Enrich — Text Analytics for Health → DNT + entities
    source_segments = yield context.call_activity("activity_enrich", {
        "jobId": job_id,
        "segments": source_segments,
    })

    # 3. Glossary lookup — pull pinned translations from Cosmos
    source_segments = yield context.call_activity("activity_glossary_lookup", {
        "jobId": job_id,
        "segments": source_segments,
        "targetLanguage": target_language,
    })

    # 4. Build per-job glossary TSV for Document Translation
    glossary = yield context.call_activity("activity_glossary_build", {
        "jobId": job_id,
        "segments": source_segments,
        "targetLanguage": target_language,
    })

    # 5. Document Translation — format-preserving translation with the per-job glossary
    doc_translate = yield context.call_activity("activity_document_translate", {
        "jobId": job_id,
        "sourceBlob": source_blob,
        "targetLanguage": target_language,
        "glossaryBlob": glossary.get("glossaryBlob"),
    })
    translated_blob = doc_translate["translatedBlob"]

    # 6. Re-extract translated docx → target segments (no enrich/glossary needed)
    target_extract = yield context.call_activity("activity_extract", {
        "jobId": job_id,
        "blobPath": translated_blob,
        "mode": "target",
    })

    # 7. Pair source ↔ target segments by document order
    paired = yield context.call_activity("activity_pair_segments", {
        "jobId": job_id,
        "sourceSegments": source_segments,
        "targetSegments": target_extract["segments"],
    })

    # 8. Guardrails — deterministic checks
    paired = yield context.call_activity("activity_guardrails", {
        "jobId": job_id,
        "segments": paired,
    })

    # 9. Judge — LLM scores quality across paired segments
    judge_result = yield context.call_activity("activity_judge", {
        "jobId": job_id,
        "segments": paired,
        "targetLanguage": target_language,
        "attempt": 1,
    })

    attempt = 1
    while (
        judge_result["decision"] == "REVISE"
        and judge_result["overall_score"] < PASS_THRESHOLD
        and attempt < MAX_REVISE_ATTEMPTS + 1
    ):
        attempt += 1
        logging.info("jobId=%s revising attempt=%s score=%s", job_id, attempt, judge_result["overall_score"])

        paired = yield context.call_activity("activity_revise", {
            "jobId": job_id,
            "segments": paired,
            "judgeFeedback": judge_result,
            "targetLanguage": target_language,
            "attempt": attempt,
        })
        paired = yield context.call_activity("activity_guardrails", {
            "jobId": job_id,
            "segments": paired,
        })
        judge_result = yield context.call_activity("activity_judge", {
            "jobId": job_id,
            "segments": paired,
            "targetLanguage": target_language,
            "attempt": attempt,
        })

    score = judge_result["overall_score"]
    decision = judge_result["decision"]

    if score < PASS_THRESHOLD:
        review = yield context.call_activity("activity_route_to_review", {
            "jobId": job_id,
            "targetLanguage": target_language,
            "segments": paired,
            "judgeResult": judge_result,
            "translatedBlob": translated_blob,
            "attempts": attempt,
        })
        return {
            "jobId": job_id,
            "status": "needs_review",
            "score": score,
            "attempts": attempt,
            "reviewBlob": review["reviewBlob"],
            "translatedBlob": translated_blob,
        }

    # 10. Patch the already-translated DOCX with any revised segments, then finalize
    final = yield context.call_activity("activity_patch_docx", {
        "jobId": job_id,
        "targetLanguage": target_language,
        "translatedBlob": translated_blob,
        "segments": paired,
        "judgeResult": judge_result,
        "attempts": attempt,
        "sourceBlob": source_blob,
    })

    return {
        "jobId": job_id,
        "status": "completed",
        "score": score,
        "attempts": attempt,
        "finalBlob": final["finalBlob"],
        "auditBlob": final["auditBlob"],
        "translatedBlob": translated_blob,
    }
