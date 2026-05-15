<#
.SYNOPSIS
  Deploy the weather agent to Azure Container Apps, generate traffic,
  and validate spans in Application Insights.

.DESCRIPTION
  Mirrors deploy.sh for Windows / PowerShell users. Requires the
  Azure CLI (`az`) and Python on PATH.

.NOTES
  Required env vars:
    RESOURCE_GROUP, LOCATION, ACA_ENV, ACR_NAME,
    APPLICATIONINSIGHTS_CONNECTION_STRING, APPINSIGHTS_RESOURCE_ID,
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT
  Optional:
    AZURE_OPENAI_API_KEY, AGENT_NAME (default weather-agent), IMAGE_TAG (default latest)
#>

$ErrorActionPreference = "Stop"

function Require-Env($name) {
  if (-not (Get-Item "Env:$name" -ErrorAction SilentlyContinue)) {
    throw "Missing required env var: $name"
  }
}

foreach ($v in @(
  "RESOURCE_GROUP","LOCATION","ACA_ENV","ACR_NAME",
  "APPLICATIONINSIGHTS_CONNECTION_STRING",
  "AZURE_OPENAI_ENDPOINT","AZURE_OPENAI_DEPLOYMENT"
)) { Require-Env $v }

$AgentName  = if ($env:AGENT_NAME)    { $env:AGENT_NAME }    else { "weather-agent" }
$OtelAgentId = if ($env:OTEL_AGENT_ID) { $env:OTEL_AGENT_ID } else { $AgentName }
$ImageTag   = if ($env:IMAGE_TAG)     { $env:IMAGE_TAG }     else { "latest" }
$Image     = "$($env:ACR_NAME).azurecr.io/${AgentName}:${ImageTag}"

Write-Host "==> Building and pushing image to ACR"
az acr build --registry $env:ACR_NAME --image "${AgentName}:${ImageTag}" . | Out-Null

Write-Host "==> Deploying to Azure Container Apps"
$envVars = @(
  "AGENT_NAME=$AgentName",
  "OTEL_AGENT_ID=$OtelAgentId",
  "APPLICATIONINSIGHTS_CONNECTION_STRING=$($env:APPLICATIONINSIGHTS_CONNECTION_STRING)",
  "AZURE_OPENAI_ENDPOINT=$($env:AZURE_OPENAI_ENDPOINT)",
  "AZURE_OPENAI_DEPLOYMENT=$($env:AZURE_OPENAI_DEPLOYMENT)",
  "AZURE_OPENAI_API_KEY=$($env:AZURE_OPENAI_API_KEY)"
)

$exists = az containerapp show -n $AgentName -g $env:RESOURCE_GROUP 2>$null
if ($LASTEXITCODE -eq 0 -and $exists) {
  az containerapp update -n $AgentName -g $env:RESOURCE_GROUP --image $Image | Out-Null
} else {
  az containerapp create `
    --name $AgentName `
    --resource-group $env:RESOURCE_GROUP `
    --environment $env:ACA_ENV `
    --image $Image `
    --target-port 8000 `
    --ingress external `
    --min-replicas 1 --max-replicas 2 `
    --registry-server "$($env:ACR_NAME).azurecr.io" `
    --env-vars $envVars | Out-Null
}

$Fqdn = az containerapp show -n $AgentName -g $env:RESOURCE_GROUP `
          --query properties.configuration.ingress.fqdn -o tsv
$AgentUrl = "https://$Fqdn"
Write-Host "==> Agent URL: $AgentUrl"

Write-Host "==> Waiting for /healthz"
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-WebRequest -UseBasicParsing -Uri "$AgentUrl/healthz" | Out-Null; break }
  catch { Start-Sleep -Seconds 5 }
}

Write-Host "==> Generating traffic"
$env:AGENT_URL = $AgentUrl
$env:AGENT_NAME = $AgentName
$env:OTEL_AGENT_ID = $OtelAgentId
python generate_traffic.py

Write-Host "==> Waiting 90s for OTel export to flush to App Insights"
Start-Sleep -Seconds 90

Write-Host "==> Validating spans landed in App Insights"
python validate_spans.py

Write-Host "==> Done. Now run: python register_external_agent.py"
