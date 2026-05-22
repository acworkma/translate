"""Enrich activity — Text Analytics for Health to surface medical entities + DNT spans.

Entities in DNT_CATEGORIES are added to `segment.dnt_terms` so downstream
prompts and guardrails know not to translate them (drug names, dosages, etc.).
"""
from __future__ import annotations

import logging
import os

import azure.durable_functions as df
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential  # noqa: F401  (kept for type clarity)

from app.clients.foundry import get_credential
from app.models import Segment

enrich_bp = df.Blueprint()

# Health categories where mistranslation = clinical risk → mark as do-not-translate
DNT_CATEGORIES = {
    "Dosage",
    "MedicationName",
    "MedicationForm",
    "MedicationRoute",
    "Frequency",
    "Time",
    "MedicationStrength",
    "Measurement",
    "Numeric",
    "Code",
}


def _ta_client() -> TextAnalyticsClient:
    # Text Analytics is part of the Foundry AIServices endpoint (Language capability)
    endpoint = os.environ["FOUNDRY_ENDPOINT"].rstrip("/")
    return TextAnalyticsClient(endpoint=endpoint, credential=get_credential())


@enrich_bp.activity_trigger(input_name="payload")
def activity_enrich(payload: dict) -> list[dict]:
    job_id = payload["jobId"]
    raw_segments = payload["segments"]
    segments = [Segment(**s) for s in raw_segments]

    if not segments:
        return []

    client = _ta_client()
    # Process in batches of 10 (TAfH limit per request)
    BATCH = 10
    for i in range(0, len(segments), BATCH):
        batch = segments[i:i + BATCH]
        docs = [{"id": str(idx), "language": "en", "text": s.source_text} for idx, s in enumerate(batch)]
        try:
            poller = client.begin_analyze_healthcare_entities(docs)
            results = list(poller.result())
        except Exception as exc:
            logging.warning("enrich jobId=%s batch=%d failed: %s — continuing without entities", job_id, i, exc)
            continue

        for idx, doc_result in enumerate(results):
            if doc_result.is_error:
                continue
            seg = batch[idx]
            for ent in doc_result.entities:
                ent_dict = {
                    "text": ent.text,
                    "category": ent.category,
                    "subcategory": getattr(ent, "subcategory", None),
                    "confidence": ent.confidence_score,
                }
                # UMLS/SNOMED/RxNorm links
                links = getattr(ent, "data_sources", None) or []
                if links:
                    ent_dict["links"] = [{"name": l.name, "entity_id": l.entity_id} for l in links]
                seg.medical_entities.append(ent_dict)

                if ent.category in DNT_CATEGORIES and ent.text not in seg.dnt_terms:
                    seg.dnt_terms.append(ent.text)

    logging.info("enrich jobId=%s entities-tagged=%d", job_id,
                 sum(len(s.medical_entities) for s in segments))
    return [s.model_dump() for s in segments]
