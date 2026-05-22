# Pediatric Discharge Translator — Function App

Azure Durable Functions (Python v2) implementation of the orchestrator described in Phase 3.

## Flow

```
HTTP POST /api/jobs
         │
         ▼
  orchestrator
   1. extract            (Content Understanding REST → segments + raw.json + image refs)
   2. enrich             (Text Analytics for Health → DNT terms + UMLS/SNOMED/RxNorm links)
   3. glossary           (Cosmos lookup → pinned translations)
   4. translate          (GPT-4.1, batched, JSON output)
   5. guardrails         (regex checks: numbers / units / placeholders / DNT)
   6. judge              (Grok-3 scores 0–5, returns PASS|REVISE|REJECT)
   7. revise loop        (up to MAX_REVISE_ATTEMPTS — only flagged segments are re-translated)
   8a. reconstruct       (PASS → write translated DOCX to final/, audit bundle to audit/)
   8b. route to review   (REJECT → write to reviewed/ for human review)
```

## Layout

```
function_app/
├── host.json
├── requirements.txt
├── local.settings.json.example
├── function_app.py             # entry: HTTP starter + status endpoint
└── app/
    ├── models.py               # Pydantic Segment, JudgeResult, JobState
    ├── orchestrator.py         # Durable orchestrator with revise loop
    ├── clients/
    │   ├── foundry.py          # AzureOpenAI w/ DefaultAzureCredential + token provider
    │   ├── cosmos.py
    │   └── blob.py
    ├── activities/
    │   ├── extract.py          # Content Understanding REST + segment flattening
    │   ├── enrich.py           # Text Analytics for Health
    │   ├── glossary.py         # Cosmos glossary query
    │   ├── translate.py        # GPT-4.1 pass 1
    │   ├── guardrails.py       # deterministic checks
    │   ├── judge.py            # Grok-3 scorer
    │   ├── revise.py           # GPT-4.1 pass 2 on flagged segments only
    │   └── reconstruct.py      # python-docx text substitution + audit bundle
    └── prompts/
        ├── translator.md
        ├── judge.md
        └── reviser.md
```

## Prerequisites

The Bicep in `../bicep/` provisions everything this app needs. Before deploying the code:

1. Deploy the Bicep (`az deployment sub create ... --parameters dev.bicepparam`).
2. Pull the output values:
   ```bash
   az deployment sub show -n dischargemt-dev --query properties.outputs
   ```
3. Create your Content Understanding analyzer (one-time) and note its ID. Recommended schema fields:
   - `paragraphs[]` with `id`, `content`, `role`
   - `tables[]` with `cells[]` with `id` and `content`
   - `figures[]` with `id` and `imageRef`
4. Set `CONTENT_UNDERSTANDING_ANALYZER_ID` in the Function App settings.

## App settings the Bicep already wires up

| Setting | Used by |
|---|---|
| `AzureWebJobsStorage__accountName` / `__credential=managedidentity` / `__clientId` | Durable runtime |
| `AZURE_CLIENT_ID` | `DefaultAzureCredential` for all M365/Azure calls |
| `FOUNDRY_ENDPOINT` | OpenAI + xAI + Language + Translator |
| `COSMOS_ENDPOINT` / `COSMOS_DATABASE` | Job state + glossary |
| `DOCUMENT_STORAGE_BLOB_ENDPOINT` | Read inbound, write artifacts |
| `MODEL_TRANSLATOR=gpt-4-1` | Translator + reviser |
| `MODEL_JUDGE=grok-3` | Judge |
| `MODEL_UTILITY=gpt-4o-mini` | (reserved) |

You must set:
| Setting | Default | Notes |
|---|---|---|
| `CONTENT_UNDERSTANDING_ANALYZER_ID` | — | ID of your CU analyzer |
| `JUDGE_PASS_THRESHOLD` | `4.0` | Overall score required to skip review |
| `MAX_REVISE_ATTEMPTS` | `2` | After this many, route to human review |

## Local development

```bash
cd function_app
cp local.settings.json.example local.settings.json
# Fill in values from Bicep outputs
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
func start
```

`DefaultAzureCredential` will use your `az login` identity locally — make sure your user has Storage Blob Data Owner on the function storage, Cognitive Services User on the Foundry account, and Cosmos DB Built-in Data Contributor.

## Deploy

```bash
cd function_app
func azure functionapp publish func-dischargemt-dev-<suffix>
```

The Flex Consumption plan has its deployment storage container provisioned via Bicep with MI access — no key wrangling.

## Try it

```bash
# 1. Upload a sample DOCX
az storage blob upload \
  --account-name st<workload><env><suffix> \
  --container-name inbound \
  --name sample-discharge.docx \
  --file ./sample-discharge.docx \
  --auth-mode login

# 2. Start a job
curl -X POST "https://func-dischargemt-dev-<suffix>.azurewebsites.net/api/jobs?code=<function-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jobId": "j-001",
    "sourceBlob": "inbound/sample-discharge.docx",
    "targetLanguage": "es-MX"
  }'

# Response includes statusQueryGetUri — poll it to watch progress.
```

When the orchestration completes:
- `final/<jobId>/<lang>/translated.docx` — translated document
- `audit/<jobId>/audit.json` — full bundle (segments + judge result + scores + attempts)
- `reviewed/<jobId>/review.json` — only if the judge couldn't reach PASS in `MAX_REVISE_ATTEMPTS`

## Glossary seeding

The glossary container is partitioned by `/language`. Seed it with any high-priority terms:

```bash
az cosmosdb sql container query \
  --account-name cosmos-... --database-name dischargemt --name glossary \
  --query-text "SELECT * FROM c WHERE c.language = 'es-MX'"
```

Document shape:
```json
{
  "id": "tylenol",
  "language": "es-MX",
  "source": "Tylenol",
  "target": "Tylenol",
  "notes": "Brand name — keep as-is"
}
```

(`id` is the lowercased source term — the glossary activity does `term.lower()` before lookup.)

## What's NOT here (yet)

| Item | Phase |
|---|---|
| Glossary admin / approval UI | 5 |
| Reviewer queue UI (the `reviewed/` blobs are the inbox) | 5 |
| PDF support (currently DOCX-only; PDFs fall back to .txt) | 4 |
| Custom Translator domain model integration | 4 |
| Private endpoint trust + key-less deployment over VNet | 5 |
| Per-tenant prompt overrides | 5 |
