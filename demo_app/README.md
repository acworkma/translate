# translate-demo

Tiny FastAPI app that fronts the translation pipeline with a dark-mode GUI for demos.

## Features
- Password gate (single password, default `fr24`, override with `DEMO_PASSWORD` env / Key Vault).
- Click-to-upload or drag-and-drop `.docx`, target-language picker.
- Live pipeline visualization (extract → enrich → glossary → DT → pair → guardrails → judge → finalize).
- Result card with judge score badge, attempts, side-by-side preview, and download button.

## Local run
```bash
cd demo_app
pip install -r requirements.txt
export FUNCTION_HOST=https://func-translate-topmsk.azurewebsites.net
export FUNCTION_KEY=$(az functionapp keys list -g rg-translate -n func-translate-topmsk --query functionKeys.default -o tsv)
export STORAGE_ACCOUNT_NAME=sttranslatetopmsk
export DEMO_PASSWORD=fr24
export SUPPORTED_LANGUAGES=es,zh-Hans,vi,ar,ru
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000.

## Container
Build/push via ACR:
```bash
az acr build -r <acr-name> -t translate-demo:latest .
```

## Environment
| var | description |
| --- | --- |
| `DEMO_PASSWORD`           | UI password gate. |
| `SESSION_SECRET`          | itsdangerous signing key. |
| `FUNCTION_HOST`           | `https://<funcapp>.azurewebsites.net`. |
| `FUNCTION_KEY`            | Function key (dev). Prefer Key Vault in prod. |
| `FUNCTION_KEY_SECRET_URI` | KV secret URI for the function key. |
| `STORAGE_ACCOUNT_NAME`    | Document storage account. |
| `SUPPORTED_LANGUAGES`     | CSV of allowed target codes. |
| `AZURE_CLIENT_ID`         | UAMI client id for `DefaultAzureCredential`. |
