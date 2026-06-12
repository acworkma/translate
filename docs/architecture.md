# Architecture

This document describes the architecture of the document translation system in two levels of detail:

1. **Overview** — high-level diagrams where each Azure service is a single box. Good for explaining the system at a glance.
2. **Detail** — full diagrams showing the Durable Functions activities, storage containers, Cosmos containers, and model deployments. Good for engineering reviews and debugging.

Each level has two diagrams: the **production Function API path** (the contract a real caller integrates against) and the **demo app overlay** (a FastAPI Container App that consumes the production API).

---

## Overview — Production path

The production surface is the Function App's HTTP API. A caller uploads a source `.docx` to the document storage `inbound/` container, then POSTs a job request to the Function App. The Function App's Durable orchestrator drives Content Understanding, Azure AI Translator (Document Translation), and Azure AI Foundry models, persisting state to Cosmos DB and final output to storage.

```mermaid
flowchart LR
    Caller([Client / API caller])
    FuncApp["Function App<br/>(Durable orchestrator)"]
    Storage[("Document Storage<br/>inbound · translated · final · reviewed · audit")]
    Cosmos[("Cosmos DB<br/>jobs · glossary · audit · reviews")]
    Foundry["Azure AI Foundry<br/>translator · judge · utility · TA4H"]
    CU["Content Understanding<br/>(document extraction)"]
    DocTx["Azure AI Translator<br/>Document Translation"]

    KV["Key Vault"]:::cross
    Obs["App Insights +<br/>Log Analytics"]:::cross

    Caller -- "1. upload .docx" --> Storage
    Caller -- "2. POST /api/jobs<br/>3. GET /api/jobs/{id}" --> FuncApp

    FuncApp <--> Storage
    FuncApp <--> Cosmos
    FuncApp --> Foundry
    FuncApp --> CU
    FuncApp --> DocTx
    DocTx <--> Storage

    KV -. function key .-> Caller
    FuncApp -. telemetry .-> Obs

    classDef cross stroke-dasharray: 4 3,fill:#f5f5f5,color:#555;
```

---

## Overview — Demo overlay

The demo is a FastAPI Container App that sits in front of the production Function API. End users authenticate against the demo (password + signed cookie), upload a `.docx`, and the demo brokers the upload-to-storage + start-job + poll-status flow on their behalf. The Function App is a black box to the demo.

```mermaid
flowchart LR
    User([End user / browser])
    Demo["Container App<br/>(demo FastAPI)"]
    FuncApp["Function App<br/>(production API)"]
    Storage[("Document Storage")]
    KV["Key Vault"]
    ACR[("ACR")]:::cross

    User -- "login + SPA" --> Demo
    User -- "upload .docx" --> Demo
    User -- "poll status / download" --> Demo

    Demo -- "PUT inbound/" --> Storage
    Demo -- "POST /api/jobs<br/>GET /api/jobs/{id}" --> FuncApp
    Demo -- "stream final / draft / review" --> Storage
    Demo -- "fetch function key" --> KV

    ACR -. image pull .-> Demo

    classDef cross stroke-dasharray: 4 3,fill:#f5f5f5,color:#555;
```

---

## Detail — Production path

Full Durable Functions activity graph. The orchestrator extracts the source via Content Understanding, enriches with Text Analytics for Health, looks up pinned glossary terms in Cosmos, builds a TSV glossary blob, runs Azure AI Translator Document Translation (format-preserving spine), re-extracts the translated output, pairs segments by reading order, runs deterministic guardrails, then scores with the Grok judge. On `REVISE`, only flagged segments are sent to the GPT-4.1 reviser and the loop re-runs guardrails + judge (up to `MAX_REVISE_ATTEMPTS`). On `PASS`, the orchestrator surgically patches only the revised segments into the Document Translation output and writes the final DOCX. On `REJECT` after retries, the job is routed to human review.

```mermaid
flowchart LR
    Caller([Client / API caller])

    subgraph Ingress["HTTP API (function key)"]
        FnStart["POST /api/jobs<br/>HTTP trigger"]
        FnStatus["GET /api/jobs/{jobId}<br/>HTTP trigger"]
    end

    subgraph FuncApp["Function App (Flex Consumption, Python 3.11)<br/>workload UAMI"]
        Orchestrator{{"Durable Orchestrator<br/>orchestrator()"}}
        AExtractSrc["activity_extract (source)"]
        AEnrich["activity_enrich"]
        AGlossLookup["activity_glossary_lookup"]
        AGlossBuild["activity_glossary_build"]
        ADocTx["activity_document_translate"]
        AExtractTgt["activity_extract (target)"]
        APair["activity_pair_segments"]
        AGuard["activity_guardrails"]
        AJudge["activity_judge"]
        ARevise["activity_revise"]
        APatch["activity_patch_docx"]
        ARoute["activity_route_to_review"]
    end

    subgraph DurableStore["Function operational storage (stfunctranslate*)"]
        DurBlobs[("Blob / Queue / Table<br/>Durable state")]
    end

    subgraph DocStorage["Document storage (sttranslate*, HNS)"]
        BInbound[("inbound/")]
        BExtracted[("extracted/")]
        BGloss[("glossaries/")]
        BTranslated[("translated/")]
        BFinal[("final/")]
        BReviewed[("reviewed/")]
        BAudit[("audit/")]
    end

    subgraph Cosmos["Cosmos DB (serverless) — db: translate"]
        CJobs[("jobs")]
        CGloss[("glossary")]
        CAudit[("audit")]
        CReviews[("reviews")]
    end

    subgraph Foundry["Azure AI Foundry (eastus2)"]
        MTrans["gpt-4-1<br/>(reviser)"]
        MJudge["grok-4-1-fast-reasoning<br/>(judge)"]
        MUtil["gpt-4o-mini<br/>(utility)"]
        TA4H["Text Analytics<br/>for Health"]
    end

    CU["Content Understanding<br/>analyzer translate_doc_v1<br/>(westus)"]
    DocTx["Azure AI Translator<br/>Document Translation API<br/>(Foundry MI → Blob)"]

    Obs["App Insights +<br/>Log Analytics"]
    KV["Key Vault<br/>(function key secret)"]

    Caller -- "1. PUT source.docx" --> BInbound
    Caller -- "2. POST jobId+sourceBlob+lang" --> FnStart
    FnStart --> Orchestrator
    Orchestrator <--> DurBlobs

    Orchestrator --> AExtractSrc --> CU
    AExtractSrc --> BExtracted
    Orchestrator --> AEnrich --> TA4H
    Orchestrator --> AGlossLookup --> CGloss
    Orchestrator --> AGlossBuild --> BGloss
    Orchestrator --> ADocTx --> DocTx
    DocTx -- reads --> BInbound
    DocTx -- writes --> BTranslated
    ADocTx -. uses .-> BGloss
    Orchestrator --> AExtractTgt --> CU
    AExtractTgt --> BExtracted
    Orchestrator --> APair
    Orchestrator --> AGuard
    Orchestrator --> AJudge --> MJudge
    Orchestrator -- "score < threshold<br/>retries < N" --> ARevise --> MTrans
    ARevise --> AGuard

    Orchestrator -- "PASS" --> APatch
    APatch -- reads --> BTranslated
    APatch -- writes --> BFinal
    APatch --> BAudit
    APatch --> CAudit
    Orchestrator -- "REJECT" --> ARoute
    ARoute --> BReviewed
    ARoute --> CReviews

    Orchestrator --> CJobs
    Caller -- "3. poll" --> FnStatus --> Orchestrator

    FuncApp -. telemetry .-> Obs
    FuncApp -. UAMI auth .-> Foundry
    FuncApp -. UAMI auth .-> Cosmos
    FuncApp -. UAMI auth .-> DocStorage
    KV -. consumed by callers .-> FnStart
```

---

## Detail — Demo overlay

The demo is a single FastAPI process in a Container App. It handles password login (signed cookie session), uploads to `inbound/` using its own UAMI, fetches the Function key from Key Vault (5-minute cache), then proxies `POST /api/jobs` and `GET /api/jobs/{id}` calls. The browser polls the demo every 4 seconds, and the demo overlays a time-based step heuristic on top of the orchestrator's `runtimeStatus`. Downloads and previews stream directly from document storage. The orchestrator details from the production diagram are intentionally shown as a black box here.

```mermaid
flowchart LR
    User([End user / browser])

    subgraph ACA["Container Apps Env (cae-translate-eus2)"]
        Demo["ca-translate-demo<br/>FastAPI + Uvicorn<br/>demo UAMI"]
    end

    ACR[("ACR<br/>acrtranslate*<br/>translate-demo image")]
    KV["Key Vault<br/>function key secret"]

    subgraph FuncBox["Function App (production API)"]
        FnJobs["POST /api/jobs"]
        FnStatus["GET /api/jobs/{jobId}"]
        OrchBlackBox{{"Durable orchestrator<br/>+ activities<br/>(see Detail — Production path)"}}
        FnJobs --> OrchBlackBox
        FnStatus --> OrchBlackBox
    end

    subgraph DocStorage["Document storage (sttranslate*)"]
        BInbound[("inbound/")]
        BTranslated[("translated/")]
        BFinal[("final/")]
        BReviewed[("reviewed/")]
    end

    User -- "GET /login<br/>POST password" --> Demo
    Demo -- "signed session cookie" --> User
    User -- "GET /app (SPA)" --> Demo

    User -- "upload .docx<br/>POST /api/jobs" --> Demo
    Demo -- "PUT inbound/{jobId}/source.docx<br/>(UAMI)" --> BInbound
    Demo -- "fetch key (5-min cache)" --> KV
    Demo -- "POST /api/jobs?code=...<br/>{jobId,sourceBlob,lang}" --> FnJobs

    User -- "poll every 4s<br/>GET /api/jobs/{jobId}" --> Demo
    Demo -- "GET /api/jobs/{jobId}?code=..." --> FnStatus
    Demo -- "step heuristic +<br/>runtimeStatus → UI" --> User

    User -- "download / preview" --> Demo
    Demo -- "stream DOCX" --> BFinal
    Demo -- "stream DT draft" --> BTranslated
    Demo -- "stream review.json" --> BReviewed

    ACR -. image pull (AcrPull) .-> Demo
```
