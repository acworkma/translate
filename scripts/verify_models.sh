#!/usr/bin/env bash
# Verify the model deployments we depend on are available in eastus2.
# Re-run after deploy to confirm gpt-4-1, gpt-4o-mini, grok-4-1-fast-reasoning are live.
set -euo pipefail

REGION="${REGION:-eastus2}"
RG="${RG:-rg-translate}"
ACCOUNT="${ACCOUNT:-aif-translate-eus2}"

echo "Available model SKUs in $REGION (filtered to what we use):"
az cognitiveservices model list -l "$REGION" \
  --query "[?contains(['gpt-4.1','gpt-4o-mini','grok-4-1-fast-reasoning'], model.name)].{name:model.name, version:model.version, format:model.format, skus:model.skus[].name | join(',', @)}" \
  -o table

echo
echo "Deployments on $ACCOUNT:"
az cognitiveservices account deployment list \
  -g "$RG" -n "$ACCOUNT" \
  --query "[].{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity}" \
  -o table
