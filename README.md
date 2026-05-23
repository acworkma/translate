# Document Translation Workflow

End-to-end Azure pipeline that translates English DOCX files into other languages while preserving format, images, and layout. Built on Durable Functions + Azure AI Translator + Azure AI Foundry models.

## Architecture

```
┌──────────────────────┐    ┌───────────────────────────┐    ┌─────────────────────────┐
│ HTTP POST /api/jobs  │ →  │ Durable Orchestrator      │ →  │ extract (Content Under- │
│ (Functions HTTP)     │    │ (Durable Functions)       │    │ standing) — paragraphs  │
└──────────────────────┘    └───────────────────────────┘    └─────────────────────────┘
                                                                       ↓
              ┌──────────────────────────────────────────────────────────────────────┐
              │ enrich (AI Language / TA4H DNT) → glossary_lookup (Cosmos DB)        │
              │ → glossary_build (Blob — TSV) → document_translate                   │
              │   (AI Translator — format preserved, images intact)                  │
              │ → extract (Content Understanding — re-read translated docx)          │
              │ → pair_segments (in-proc) → guardrails (in-proc) → judge (Foundry —  │
              │   Grok) → revise loop (Foundry — gpt-4.1) → patch_docx (Blob)        │
              │ → final/ (Blob)                                                      │
              └──────────────────────────────────────────────────────────────────────┘
```

**Why hybrid?** Azure AI Translator's Document Translation API preserves the original DOCX exactly — images, tables, fonts, footers — but cannot enforce a medical glossary or self-evaluate. We use it as the format-preserving spine, then run an LLM judge over the paired (source ↔ target) segments and surgically patch only the segments the judge flagged. Untouched paragraphs keep all their original run-level formatting.

## Layout

```
bicep/         Infrastructure (subscription-scope)
  main.bicep                  RG + workload dispatch
  workload.bicep              all module wiring
  translate.bicepparam        parameters
  modules/                    7 modules
function_app/  Python 3.11 Durable Functions app
  function_app.py             HTTP starters
  app/orchestrator.py         hybrid flow
  app/clients/                foundry, blob, cosmos
  app/activities/             12 activities
  app/prompts/                judge.md, reviser.md, translator.md
scripts/       create_cu_analyzer.py, seed_glossary.py, verify_models.sh, make_sample_doc.py
data/          glossary_seed.tsv, sample_discharge.docx (generated)
```

## Deploy

Prereqs: Azure CLI logged in to subscription `ME-MngEnvMCAP818246-adworkma-1`, Bicep CLI ≥ 0.43, Node.js (for Functions Core Tools).

```bash
# 1. Install Functions Core Tools v4 if missing
npm i -g azure-functions-core-tools@4 --unsafe-perm true

# 2. Deploy infra (subscription scope creates rg-translate)
az deployment sub create \
  -n translate \
  -l eastus2 \
  --template-file bicep/main.bicep \
  --parameters bicep/translate.bicepparam

# 3. Capture outputs
FUNC_APP=$(az deployment sub show -n translate --query properties.outputs.functionAppName.value -o tsv)
STORAGE=$(az deployment sub show -n translate --query properties.outputs.storageAccountName.value -o tsv)
echo "Function app: $FUNC_APP / Storage: $STORAGE"

# 4. Verify model deployments
bash scripts/verify_models.sh

# 5. Create the Content Understanding analyzer
FOUNDRY_ENDPOINT=https://aif-translate-eus2.cognitiveservices.azure.com \
  python scripts/create_cu_analyzer.py

# 6. Seed the glossary
COSMOS_ENDPOINT=$(az deployment sub show -n translate --query properties.outputs.cosmosEndpoint.value -o tsv) \
  COSMOS_DATABASE=translate \
  python scripts/seed_glossary.py data/glossary_seed.tsv

# 7. Publish function code
cd function_app
func azure functionapp publish "$FUNC_APP" --python
cd ..
```

## Smoke test

```bash
# Generate the synthetic discharge summary
pip install python-docx
python scripts/make_sample_doc.py

# Upload to inbound
az storage blob upload \
  --account-name "$STORAGE" --auth-mode login \
  -c inbound -n test-001/source.docx \
  -f data/sample_discharge.docx

# Start a translation job
FUNC_KEY=$(az functionapp keys list -g rg-translate -n "$FUNC_APP" --query functionKeys.default -o tsv)
curl -X POST "https://$FUNC_APP.azurewebsites.net/api/jobs?code=$FUNC_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jobId":"test-001","sourceBlob":"inbound/test-001/source.docx","targetLanguage":"es"}'

# Poll until completed
curl "https://$FUNC_APP.azurewebsites.net/api/jobs/test-001?code=$FUNC_KEY"

# Download the result
az storage blob download \
  --account-name "$STORAGE" --auth-mode login \
  -c final -n test-001/es/source.docx \
  -f /tmp/source.es.docx
open /tmp/source.es.docx
```

Supported languages out of the box: `es`, `zh-Hans`, `vi`, `ar`, `ru` (configurable via `SUPPORTED_LANGUAGES` app setting).

## Models

| Role         | Setting             | Model                       |
| ------------ | ------------------- | --------------------------- |
| Translator   | `MODEL_TRANSLATOR`  | `gpt-4-1` (gpt-4.1)         |
| Judge        | `MODEL_JUDGE`       | `grok-4-1-fast-reasoning`   |
| Utility      | `MODEL_UTILITY`     | `gpt-4o-mini`               |

All three are deployed inside the same `aif-translate-eus2` AI Services account.

## Auth model

- Workload UAMI `id-translate-eus2` attached to the function app and used for: Cognitive Services User on the AIServices account, OpenAI User, Blob Data Contributor on doc storage, Queue/Table/Blob Data on func ops storage, Cosmos SQL Built-in Data Contributor on the translate DB, KV Secrets User.
- AIServices account's system MI also has Blob Data Contributor on doc storage — Azure AI Translator uses this to read the source and write the translated DOCX.
- All storage accounts: `allowSharedKeyAccess: false`. Cosmos: `disableLocalAuth: true`. App Insights: `DisableLocalAuth: true`.
