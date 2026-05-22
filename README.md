# Pediatric Discharge Translator — Bicep (Phase 0/1/3)

Deployable scaffold for the foundations, AI Foundry resources, and the Phase 3 orchestration layer.

## What this deploys

| Resource | Purpose |
|---|---|
| Resource Group | Container for all workload resources |
| User-Assigned Managed Identity | Single auth principal for Function App and other compute |
| Log Analytics Workspace | Logs sink |
| Application Insights (workspace-based) | App telemetry, local auth disabled |
| Storage Account — documents (ADLS Gen2, GZRS) | 6 containers pre-created. Shared-key auth disabled. |
| Storage Account — function operations (LRS) | Dedicated runtime storage for the Function App (Durable queues/tables) |
| Key Vault (RBAC, purge-protected) | Secrets, certs |
| Azure AI Foundry account (kind=AIServices) | Unified endpoint for Content Understanding, Language (TAfH), Translator, AOAI, xAI |
| Foundry project | Hosts agents, prompt flows, evals |
| GPT-4.1 deployment | Translator (Pass 1 + Pass 2) |
| GPT-4o-mini deployment | Utility / readability passes |
| **Grok-3 deployment (xAI)** | **Judge model — different vendor from translator to reduce self-preference bias** |
| **Cosmos DB (SQL API, serverless)** | **Job state, glossary, audit, reviewer queue (4 containers)** |
| **Function App (Flex Consumption, Python 3.11)** | **Durable Functions orchestrator: Extract → Translate → Judge → Revise → Reconstruct** |

RBAC granted to the workload managed identity:
- Storage Blob Data Contributor on the document storage
- Storage Blob Data Owner + Queue/Table Data Contributor on the function storage
- Key Vault Secrets User on the vault
- Cognitive Services User + Cognitive Services OpenAI User on the Foundry account
- Cosmos DB Built-in Data Contributor on the Cosmos account

RBAC granted to the admin principal:
- Key Vault Administrator
- Azure AI Developer
- Cosmos DB Built-in Data Contributor

## Layout

```
bicep/
├── main.bicep               # subscription scope — creates RG, dispatches workload
├── workload.bicep           # RG scope — composes modules
├── dev.bicepparam           # parameters (edit before deploying)
├── modules/
│   ├── identity.bicep       # User-assigned managed identity
│   ├── monitoring.bicep     # Log Analytics + App Insights
│   ├── storage.bicep        # Document storage (ADLS Gen2)
│   ├── keyvault.bicep       # Key Vault
│   ├── aiFoundry.bicep      # AIServices account + project + 3 model deployments (GPT-4.1, GPT-4o-mini, Grok-3)
│   ├── cosmos.bicep         # Cosmos DB account + database + 4 containers
│   └── functions.bicep      # Function App + Flex Consumption plan + dedicated storage
└── README.md
```

## Prerequisites

- Azure CLI 2.60+
- An Azure subscription with the HIPAA BAA in place
- Quota in the chosen region for:
  - `gpt-4.1` GlobalStandard (translator)
  - `gpt-4o-mini` GlobalStandard (utility)
  - `grok-3` GlobalStandard (judge) — xAI models are pay-per-token MaaS
- Your Entra user/group object ID for `adminPrincipalId`

```bash
az ad signed-in-user show --query id -o tsv     # for an individual
# or
az ad group show --group "DischargeMT-Admins" --query id -o tsv
```

### Confirm model availability in your region

xAI Grok availability has expanded but isn't every region. Before deploying:

```bash
az cognitiveservices model list \
  --location eastus2 \
  --query "[?model.format=='xAI' || model.format=='OpenAI'].{name:model.name, version:model.version, format:model.format, sku:model.skus[0].name}" \
  -o table
```

If `grok-3` isn't listed in your region:
- Switch to **East US 2**, **West US 3**, or **Sweden Central** (most likely to have xAI)
- Or temporarily swap the judge to `gpt-4o` (different model than the translator, still useful for cross-model judging) by editing `modelDeployments` in `modules/aiFoundry.bicep`

## Deploy

```bash
# 1) Set context
az account set --subscription <subscription-id>

# 2) Edit dev.bicepparam — set adminPrincipalId

# 3) What-if (preview)
az deployment sub what-if \
  --name dischargemt-dev \
  --location eastus2 \
  --parameters dev.bicepparam

# 4) Deploy
az deployment sub create \
  --name dischargemt-dev \
  --location eastus2 \
  --parameters dev.bicepparam

# 5) Pull outputs
az deployment sub show -n dischargemt-dev --query properties.outputs
```

## After deployment — Phase 3 next steps

The infrastructure is in place. Now you write the Functions code.

### Function App project skeleton (Python v2 programming model)

```
function_app/
├── host.json
├── requirements.txt
├── function_app.py              # entry point — defines all functions
└── app/
    ├── orchestrator.py          # Durable orchestrator
    ├── activities/
    │   ├── extract.py           # Content Understanding analyzer
    │   ├── enrich.py            # Text Analytics for Health → DNT + entities
    │   ├── glossary.py          # Cosmos lookup, pinned translations
    │   ├── translate.py         # AOAI / GPT-4.1 call with prompt
    │   ├── guardrails.py        # numeric/unit/placeholder checks
    │   ├── judge.py             # Grok-3 call with scoring prompt
    │   ├── revise.py            # second-pass translation
    │   └── reconstruct.py       # python-docx output
    ├── clients/
    │   ├── foundry.py           # AzureOpenAI + REST clients via DefaultAzureCredential
    │   ├── cosmos.py
    │   └── blob.py
    └── prompts/
        ├── translator.md
        ├── judge.md
        └── reviser.md
```

### Key app settings already wired by the Bicep

| Setting | Value | Used for |
|---|---|---|
| `AZURE_CLIENT_ID` | workload MI client ID | `DefaultAzureCredential` picks the right identity |
| `FOUNDRY_ENDPOINT` | `https://aif-<workload>-<env>.cognitiveservices.azure.com/` | OpenAI + xAI + Language + Translator calls |
| `COSMOS_ENDPOINT` | Cosmos URI | Job state + glossary |
| `COSMOS_DATABASE` | `dischargemt` | Database name |
| `DOCUMENT_STORAGE_BLOB_ENDPOINT` | document storage blob endpoint | Read inbound, write artifacts |
| `MODEL_TRANSLATOR` | `gpt-4-1` | Pass 1/2 translation |
| `MODEL_JUDGE` | `grok-3` | Scoring |
| `MODEL_UTILITY` | `gpt-4o-mini` | Cheap rewrites, readability checks |

### Calling Grok from Python

Grok deployed under the AIServices account is OpenAI-compatible — use the `openai` SDK pointed at the Foundry endpoint:

```python
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_endpoint=os.environ["FOUNDRY_ENDPOINT"],
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21",
)

# Same call shape works for gpt-4-1 (translator) and grok-3 (judge)
result = client.chat.completions.create(
    model=os.environ["MODEL_JUDGE"],   # 'grok-3'
    messages=[
        {"role": "system", "content": judge_system_prompt},
        {"role": "user",   "content": judge_user_payload},
    ],
    response_format={"type": "json_object"},
    temperature=0.0,
)
```

### Deploy the function code

```bash
cd function_app
func azure functionapp publish <function-app-name>
```

(The Flex Consumption deployment-storage container is already provisioned and the MI has access — no key wrangling.)

## What's intentionally NOT in this scaffold (yet)

| Item | When to add |
|---|---|
| Private endpoints + VNet + Private DNS zones | Phase 5 hardening |
| Custom Translator workspace | Phase 4 |
| Review UI (Power Apps or React + Static Web Apps) | Phase 5 |
| Front Door + WAF | Phase 5 |
| Customer-managed keys (CMK) | Phase 5 if required |

## Region notes

- **East US 2** — most complete service coverage including xAI Grok.
- **West US 3** — strong coverage, often has newer model versions earlier.
- **Sweden Central** — EU sovereignty option with good model coverage.
- If GPT-4.1 isn't in your region, swap to `gpt-4o` version `2024-11-20`.
- If Grok-3 isn't in your region, swap the judge to `gpt-4o` (still cross-model vs. `gpt-4.1` translator — different family is the goal).

## Safety gates before going to production

- [ ] AOAI **and** xAI abuse-monitoring opt-out approved (required for PHI)
- [ ] HIPAA BAA confirmed on subscription
- [ ] Private endpoints in place; `publicNetworkAccess: 'Disabled'` everywhere
- [ ] `disableLocalAuth: true` on Foundry account
- [ ] Customer-managed keys evaluated
- [ ] Log redaction policy confirmed (no PHI in App Insights / Log Analytics)
- [ ] Diagnostic settings forwarding to LAW for: Foundry account, both Storage accounts, Key Vault, Cosmos, Function App
- [ ] Cosmos point-in-time restore enabled (production)
- [ ] Function App access restricted (Front Door + IP allowlist, or VNet-only)
