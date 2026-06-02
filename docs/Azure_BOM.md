# Azure Bill of Materials (BOM)

Assumptions for proposed quantities:
- Single production environment deployment.
- Qty is per deployed instance/resource/model deployment.
- Optional demo section applies only when `deployDemoApp=true`.
- Workload assumption: ~700,000 translated words per month.
- Industry rule of thumb: 250 words per page (English business prose) and ~5 characters per word.
- Derived volumes: ~47 documents per day, 2 pages per document, 30 days per month → 2,820 pages/month ≈ 705,000 words/month.
- No specific SLA assumption is applied.
- Deployment scope assumption: MVP implementation, not a full enterprise-scale deployment.

## Estimated Monthly Costs

- Core production subtotal: **$96.70/month**
- Optional demo subtotal (known charges): **$161.39/month**
- Optional demo additional charge not included in subtotal: **Container Apps workload profile VM hourly charges**
- Combined subtotal (core + optional demo known charges): **$258.09/month**

Notes:
- Totals above are based on the populated `Estimated Cost` values in this document.
- Combined subtotal excludes the unresolved workload profile VM hourly meter component from `Azure Container Apps Environment`.

## Core Production Services

| Qty | Unit of Measure | Azure Service | Recommended GA Version/Model | Service Tier | Role/Purpose | Cost per Unit | Estimated Units | Estimated Cost |
|---|---|---|---|---|---|---|---|---|
| 1 | Executions + GB-seconds (plus always-ready GB-seconds if enabled) | Azure Functions | Functions runtime v4 (GA) | Flex Consumption (FC1) | Hosts the HTTP API and Durable orchestration runtime for translation jobs. | On-demand: $0.000026 per 1 GB-second; executions: $0.000002 per 10; always-ready: $0.000016 per 1 GB-second (eastus2) | 16,920 executions/month; 16,920 GB-s on-demand; 0 GB-s always-ready | $0.44/month |
| 1 | GB-month (capacity) + operations (per 10K) + data transfer (GB) | Azure Storage Account | General-purpose v2 (StorageV2) with HNS (GA) | Standard GPv2, RA-GZRS (enterprise HA) | Stores source documents, extracted artifacts, glossaries, translated drafts, final outputs, and audit artifacts. | Meter sample (eastus2): $0.3038 per 1 GB-month (Standard GZRS) and $0.0015 per 10K operations | 5.51 GB-month; 8.46 (10K ops units) | $1.69/month |
| 1 | GB-month (capacity) + operations (per 10K) + data transfer (GB) | Azure Storage Account | General-purpose v2 (StorageV2) (GA) | Standard GPv2, ZRS (or GZRS per DR policy) | Provides Blob/Queue/Table storage used by Function App deployment and Durable state management. | Meter sample (eastus2): $0.3038 per 1 GB-month (Standard GZRS) and $0.0015 per 10K operations | 1.41 GB-month; 2.82 (10K ops units) | $0.43/month |
| 1 | Characters translated (typically per 1M characters) | Azure AI Translator | Document Translation API 2024-05-01 (GA) | Standard S1 (single-service Translator resource) | Performs format-preserving DOCX translation as the primary translation spine. | $15 per 1M characters (Foundry Tools, Translator Text S1, eastus2) | 3.525 (1M character units) | $52.88/month |
| 1 | Content units (for example pages/minutes) + model tokens (per 1M) | Azure AI Content Understanding | API 2025-11-01 (GA) | Usage-based GA (Standard mode in GA API) | Extracts structured content from source and translated documents for segment-level processing. | Doc extraction standard: $5 per 1K; contextualization: $0.001 per 1K tokens (eastus2) | 1.41 (1K doc units); 846 (1K contextualization-token units) | $7.90/month |
| 1 | Text records (1 record up to 1,000 chars) | Azure AI Language | Text Analytics for Health (GA) | Standard S | Enriches medical text with healthcare-specific entity/context signals used by the pipeline. | Meter sample (eastus2): Azure Language Standard from $0.25 to $2 per 1K records | 3.525 (1K record units) | $3.53/month (using $1.00 per 1K midpoint) |
| 1 | Tokens (input/output, per 1M tokens) | Azure OpenAI model deployment | GPT-5.1 family (latest GA where regionally available) | Data Zone Standard | Revises flagged segments during the quality-improvement loop. | GPT-5 Data Zone sample: $16.5 per 1M tokens (Foundry Models meter sample, eastus2) | 0.939 (1M token units, input basis) | $15.50/month |
| 1 | Tokens (input/output, per 1M tokens) | Azure OpenAI model deployment | GPT-5.1-mini (latest GA where regionally available) | Data Zone Standard | Supports utility/model-assist tasks in the workflow. | GPT-5 mini Data Zone sample: $1.65 per 1M tokens (Foundry Models meter sample, eastus2) | 0.939 (1M token units, input basis) | $1.55/month |
| 1 | Tokens (input/output, per 1M tokens) | xAI Grok model deployment via Azure AI Services | Latest GA Grok reasoning model available in region | Global Standard or Global Provisioned (based on latency SLO) | Judges translated segment quality and decides pass/revise/reject behavior. | Grok meter sample (eastus2): input from $0.0002 per 1K; output from $0.00055 per 1K | 234.77 (1K input-token units) + 258.69 (1K output-token units), using 25% review rate | $0.19/month |
| 1 | RU/s (or max RU/s autoscale) per hour + storage GB-month | Azure Cosmos DB for NoSQL | API for NoSQL (GA) | Provisioned throughput with Autoscale (container-level) | Stores job state, glossary terms, audit records, and review routing data. | Manual RU: $0.008 per 100 RU/s-hour; autoscale: $0.012 per 100 RU/s-hour (eastus2) | 19.58 (100 RU/s-hour units); 0.54 GB-month data | $0.16/month (RU throughput only) |
| 1 | Transactions (typically per 10K operations) + premium key version/month | Azure Key Vault | Azure Key Vault (GA) | Premium (HSM-backed keys) | Stores secrets such as the function key used by clients/demo broker. | Premium operations: $0.03 per 10K; premium key meter sample: $3 per key/month (eastus2) | 0.564 (10K operation units); 3 premium keys | $9.02/month |
| 1 | Data ingested (GB) and retention via Log Analytics workspace meters | Azure Application Insights | Workspace-based Application Insights (GA) | Workspace-based (Log Analytics backed) | Collects application telemetry, traces, and runtime diagnostics. | Billed via Log Analytics: $2.3 per GB ingest; $0.12 per GB-month retention (eastus2) | 0.275 GB ingest; 1.0 GB retained | $0.75/month |
| 1 | Data ingested (GB/day commitment or pay-go GB) + retention | Azure Log Analytics Workspace | Log Analytics Workspace (GA) | Commitment tier (capacity reservation) | Central log storage and analytics backend for monitoring and troubleshooting. | Analytics logs: $2.3 per GB ingest; retention: $0.12 per GB-month; 200 GB/day commitment meter: $368 per day (eastus2) | 1.0 GB ingest; 3.0 GB retained (pay-go) | $2.66/month |
| 1 | No charge | Azure Managed Identity | Managed identities for Azure resources (GA) | No SKU/tier (platform feature) | Provides passwordless authentication and RBAC-based access between services. | $0 (no direct meter) | N/A | $0.00/month |

## Optional Demo Services (when demo app is enabled)

| Qty | Unit of Measure | Azure Service | Recommended GA Version/Model | Service Tier | Role/Purpose | Cost per Unit | Estimated Units | Estimated Cost |
|---|---|---|---|---|---|---|---|---|
| 1 | Dedicated plan management fee + workload profile instance usage | Azure Container Apps Environment | Workload profiles environment (v2, GA) | Dedicated plan (production) with workload profiles | Runs the managed environment for the demo frontend API container. | Dedicated plan meter samples (eastus2): $0.1 per hour management + profile VM hourly meters | 720 management hours/month; 720 workload profile instance-hours | $72.00/month + workload profile VM hourly charges |
| 1 | vCPU-seconds + GiB-seconds (+ requests in consumption scenarios) | Azure Container App | Container Apps on workload profiles (GA) | Dedicated workload profile (General purpose) for steady enterprise workloads | Hosts the FastAPI demo app that brokers uploads and job status calls. | Consumption meter samples (eastus2): $0.000024 per vCPU-second; $0.000003 per GiB-second; $0.4 per 1M requests | 1,296,000 vCPU-s; 2,592,000 GiB-s; 0.015 (1M request units) | $38.89/month |
| 1 | Registry daily rate + additional storage (GiB-day) | Azure Container Registry | Azure Container Registry (GA) | Premium | Stores the demo container image deployed to Container Apps. | Premium: $1.6666 per day + $0.1 per GB-month additional storage (eastus2) | 30 days; 5 GB additional storage | $50.50/month |

## Notes: Estimated Units Formulas

Use these baseline assumptions for monthly estimates:
- Documents per day (`D`) = 47
- Pages per document (`P`) = 2
- Days per month (`M`) = 30
- Pages per month = `D * P * M = 2,820`
- Words per month = `Pages * W = 2,820 * 250 ≈ 705,000`

Use these helper variables where needed:
- Average words per page (`W`) = industry rule of thumb: **250** (English business prose, single-spaced)
- Average characters per page (`C`) = `W * 5` ≈ **1,250** (using 5 chars/word English average)
- Average source tokens per page (`Tsrc`) = user input
- Average output tokens per page (`Tout`) = user input
- Function executions per document (`Fdoc`) = user input (for orchestration fan-out/fan-in)

Planning defaults used for populated `Estimated Units` and `Estimated Cost`:
- `W = 250` words/page (industry rule of thumb)
- `C = 1,250` chars/page (5 chars/word)
- `Tsrc = 333` tokens/page (~1.33 tokens/word)
- `Tout = 367` tokens/page (~10% expansion over source)
- `Fdoc = 12` function executions/document
- `AvgExecutionSeconds = 2`
- `AvgMemoryGB = 0.5`
- `AvgInputMB = 1`, `AvgOutputMB = 1`, `AvgIntermediateMB = 2`
- `OpsPerDoc (data storage) = 60`; `OpsPerDoc (platform storage) = 20`
- `TokensPerPageForContext = 300`
- `GrokReviewRate = 25%`
- `AvgRUPerDoc = 5,000`
- `AvgItemKB = 8`; `ItemsPerDoc = 50`
- `KVOperationsPerDoc = 4`; `NumberOfPremiumKeys = 3`
- `TelemetryMBPerDoc = 0.2`; `AvgRetainedGB (App Insights) = 1.0`
- `Log Analytics pay-go assumption: 1.0 GB ingest, 3.0 GB retained per month`
- Optional demo: `ReplicaCount = 1`, `vCPUPerReplica = 0.5`, `GiBPerReplica = 1.0`, `DemoRequestsPerMonth = 15,000`, `AvgStoredImageGB = 5`

Suggested formulas for the `Estimated Units` column:

- Azure Functions
	- Executions (per month): `D * M * Fdoc`
	- GB-seconds (per month): `Executions * AvgExecutionSeconds * AvgMemoryGB`

- Azure Storage Account (both rows)
	- Capacity GB-month: `((AvgInputMB + AvgOutputMB + AvgIntermediateMB) * D * M) / 1024`
	- Operations in 10K units: `(OpsPerDoc * D * M) / 10000`

- Azure AI Translator
	- Characters in 1M units: `(D * P * M * C) / 1000000`

- Azure AI Content Understanding
	- Doc extraction in 1K units: `(D * M) / 1000`
	- Contextualization token units (1K): `(D * P * M * TokensPerPageForContext) / 1000`

- Azure AI Language
	- Text records in 1K units (1 record <= 1,000 chars): `(D * P * M * C) / 1000 / 1000`

- Azure OpenAI GPT-5 / GPT-5-mini / Grok
	- Input token units (1M): `(D * P * M * Tsrc) / 1000000`
	- Output token units (1M): `(D * P * M * Tout) / 1000000`

- Azure Cosmos DB for NoSQL
	- RU/s-hour units (100 RU/s-hour): `((AvgRUPerDoc * D * M) / 3600) / 100`
	- Storage GB-month: `((AvgItemKB * ItemsPerDoc * D * M) / 1024 / 1024)`

- Azure Key Vault
	- Operations in 10K units: `(KVOperationsPerDoc * D * M) / 10000`
	- Premium key versions/month: `NumberOfPremiumKeys`

- Application Insights / Log Analytics
	- Ingestion GB: `(TelemetryMBPerDoc * D * M) / 1024`
	- Retention GB-month: `AvgRetainedGB`

- Managed Identity
	- Estimated units: `N/A` (no direct billable meter)

- Optional demo: Container Apps Environment
	- Management hours: `24 * M`
	- Workload profile instance-hours: `ReplicaCount * 24 * M`

- Optional demo: Container App
	- vCPU-seconds: `vCPUPerReplica * ReplicaSeconds`
	- GiB-seconds: `GiBPerReplica * ReplicaSeconds`
	- Requests (1M units): `(DemoRequestsPerMonth) / 1000000`

- Optional demo: Container Registry
	- Registry days: `M`
	- Additional storage GB-month: `AvgStoredImageGB`

Final cost formula for each row:
- `Estimated Cost = Cost per Unit * Estimated Units`
