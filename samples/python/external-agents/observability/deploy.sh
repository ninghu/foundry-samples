#!/usr/bin/env bash
# Deploy the weather agent to Azure Container Apps, drive traffic, and
# validate that OTel spans land in Application Insights.
#
# Required env vars:
#   RESOURCE_GROUP                     - existing RG
#   LOCATION                           - e.g. eastus2
#   ACA_ENV                            - existing Container Apps env name
#   ACR_NAME                           - existing Azure Container Registry
#   APPLICATIONINSIGHTS_CONNECTION_STRING
#   APPINSIGHTS_RESOURCE_ID            - ARM resource ID of the App Insights component (used by validate_spans.py)
#   AZURE_OPENAI_ENDPOINT
#   AZURE_OPENAI_DEPLOYMENT
#   AZURE_OPENAI_API_KEY               - or rely on AAD via DefaultAzureCredential
#
# Optional:
#   AGENT_NAME      (default: weather-agent)
#   IMAGE_TAG       (default: latest)

set -euo pipefail

AGENT_NAME="${AGENT_NAME:-weather-agent}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${ACR_NAME}.azurecr.io/${AGENT_NAME}:${IMAGE_TAG}"

: "${RESOURCE_GROUP:?}"; : "${LOCATION:?}"; : "${ACA_ENV:?}"; : "${ACR_NAME:?}"
: "${APPLICATIONINSIGHTS_CONNECTION_STRING:?}"
: "${AZURE_OPENAI_ENDPOINT:?}"; : "${AZURE_OPENAI_DEPLOYMENT:?}"

echo "==> Building and pushing image to ACR"
az acr build \
  --registry "$ACR_NAME" \
  --image "${AGENT_NAME}:${IMAGE_TAG}" \
  .

echo "==> Deploying to Azure Container Apps"
az containerapp create \
  --name "$AGENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ACA_ENV" \
  --image "$IMAGE" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 2 \
  --registry-server "${ACR_NAME}.azurecr.io" \
  --env-vars \
    AGENT_NAME="$AGENT_NAME" \
    OTEL_AGENT_ID="${OTEL_AGENT_ID:-$AGENT_NAME}" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$APPLICATIONINSIGHTS_CONNECTION_STRING" \
    AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
    AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT" \
    AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY:-}" \
  --output none \
  || az containerapp update \
       --name "$AGENT_NAME" \
       --resource-group "$RESOURCE_GROUP" \
       --image "$IMAGE" \
       --output none

FQDN=$(az containerapp show -n "$AGENT_NAME" -g "$RESOURCE_GROUP" \
        --query properties.configuration.ingress.fqdn -o tsv)
AGENT_URL="https://${FQDN}"
echo "==> Agent URL: $AGENT_URL"

echo "==> Waiting for /healthz"
for i in {1..30}; do
  if curl -fsS "${AGENT_URL}/healthz" >/dev/null; then break; fi
  sleep 5
done

echo "==> Generating traffic"
AGENT_URL="$AGENT_URL" AGENT_NAME="$AGENT_NAME" OTEL_AGENT_ID="${OTEL_AGENT_ID:-$AGENT_NAME}" python generate_traffic.py

echo "==> Waiting 90s for OTel export to flush to App Insights"
sleep 90

echo "==> Validating spans landed in App Insights"
AGENT_NAME="$AGENT_NAME" python validate_spans.py

echo "==> Done. Now run: python register_external_agent.py"
