#!/bin/bash
# =============================================================================
# Deploy OR Voice Assistant to Azure Container Apps
#
# This script:
#   1. Creates a resource group (if needed)
#   2. Deploys infrastructure via Bicep (ACR, Container Apps Environment, Container App)
#   3. Builds and pushes the Docker image to ACR
#   4. Updates the container app with the new image
#   5. Grants the managed identity Cognitive Services User role
#
# Prerequisites:
#   - Azure CLI logged in (az login)
#   - .env file in the repo root with PROJECT_ENDPOINT, SPEECH_KEY, etc.
#
# Usage:
#   ./deploy.sh                          # Deploy with defaults
#   ./deploy.sh --resource-group myRg    # Custom resource group
#   ./deploy.sh --location westeurope    # Custom location
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults ---
RESOURCE_GROUP="rg-or-assistant"
LOCATION="swedencentral"
APP_NAME="or-assistant"

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
        --location) LOCATION="$2"; shift 2 ;;
        --app-name) APP_NAME="$2"; shift 2 ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
done

# --- Load .env ---
ENV_FILE="$SCRIPT_DIR/../.env"
if [[ -f "$ENV_FILE" ]]; then
    echo -e "${CYAN}[1/6] Loading configuration from .env...${NC}"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo -e "${RED}[Error] .env file not found at $ENV_FILE${NC}"
    echo "Create it with PROJECT_ENDPOINT, SPEECH_KEY, SPEECH_REGION, AGENT_ID"
    exit 1
fi

# Validate required vars
for var in PROJECT_ENDPOINT SPEECH_KEY SPEECH_REGION; do
    if [[ -z "${!var:-}" ]]; then
        echo -e "${RED}[Error] Missing required env var: $var${NC}"
        exit 1
    fi
done

AGENT_ID="${AGENT_ID:-playwright-agent}"

# --- Create resource group ---
echo -e "${CYAN}[2/6] Ensuring resource group '${RESOURCE_GROUP}' exists...${NC}"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none
echo -e "${GREEN}[2/6] Resource group ready.${NC}"

# --- Deploy Bicep infrastructure ---
echo -e "${CYAN}[3/6] Deploying infrastructure (Bicep)...${NC}"
DEPLOY_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$SCRIPT_DIR/infra/main.bicep" \
    --parameters \
        projectEndpoint="$PROJECT_ENDPOINT" \
        speechKey="$SPEECH_KEY" \
        speechRegion="$SPEECH_REGION" \
        agentId="$AGENT_ID" \
        appName="$APP_NAME" \
    --query "properties.outputs" \
    -o json)

ACR_NAME=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['acrName']['value'])")
ACR_LOGIN_SERVER=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['acrLoginServer']['value'])")
CONTAINER_APP_NAME=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['containerAppName']['value'])")
PRINCIPAL_ID=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['principalId']['value'])")
APP_URL=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['containerAppUrl']['value'])")

echo -e "${GREEN}[3/6] Infrastructure deployed.${NC}"
echo -e "  ACR: ${ACR_LOGIN_SERVER}"
echo -e "  App: ${CONTAINER_APP_NAME}"

# --- Build and push container image ---
echo -e "${CYAN}[4/6] Building container image in ACR...${NC}"
IMAGE_TAG="${ACR_LOGIN_SERVER}/${APP_NAME}-backend:$(date +%Y%m%d%H%M%S)"

az acr build \
    --registry "$ACR_NAME" \
    --image "${APP_NAME}-backend:$(date +%Y%m%d%H%M%S)" \
    --file "$SCRIPT_DIR/Dockerfile" \
    "$SCRIPT_DIR" \
    -o none

# Get the latest image tag
LATEST_IMAGE=$(az acr repository show-tags \
    --name "$ACR_NAME" \
    --repository "${APP_NAME}-backend" \
    --orderby time_desc \
    --top 1 \
    -o tsv)
FULL_IMAGE="${ACR_LOGIN_SERVER}/${APP_NAME}-backend:${LATEST_IMAGE}"

echo -e "${GREEN}[4/6] Image built: ${FULL_IMAGE}${NC}"

# --- Update container app with new image ---
echo -e "${CYAN}[5/6] Updating container app with new image...${NC}"
az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$FULL_IMAGE" \
    -o none

echo -e "${GREEN}[5/6] Container app updated.${NC}"

# --- Grant Cognitive Services User role ---
echo -e "${CYAN}[6/6] Granting Cognitive Services User role...${NC}"

# Extract AI Services resource info from PROJECT_ENDPOINT
# Format: https://<resource-name>.services.ai.azure.com/api/projects/<project>
AI_RESOURCE_NAME=$(echo "$PROJECT_ENDPOINT" | sed -n 's|https://\([^.]*\)\.services\.ai\.azure\.com.*|\1|p')

if [[ -n "$AI_RESOURCE_NAME" ]]; then
    # Find the resource ID
    AI_RESOURCE_ID=$(az cognitiveservices account list \
        --query "[?name=='${AI_RESOURCE_NAME}'].id" \
        -o tsv 2>/dev/null || true)

    if [[ -n "$AI_RESOURCE_ID" ]]; then
        az role assignment create \
            --assignee "$PRINCIPAL_ID" \
            --role "Cognitive Services User" \
            --scope "$AI_RESOURCE_ID" \
            -o none 2>/dev/null || echo -e "${YELLOW}  Role already assigned (or insufficient permissions).${NC}"
        echo -e "${GREEN}[6/6] Role assigned on ${AI_RESOURCE_NAME}.${NC}"
    else
        echo -e "${YELLOW}[6/6] Could not find AI Services resource '${AI_RESOURCE_NAME}'. Grant role manually:${NC}"
        echo -e "  az role assignment create --assignee $PRINCIPAL_ID --role 'Cognitive Services User' --scope <resource-id>"
    fi
else
    echo -e "${YELLOW}[6/6] Could not parse AI resource from PROJECT_ENDPOINT. Grant role manually.${NC}"
fi

# --- Done ---
echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  Deployment complete!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo -e "  App URL: ${APP_URL}"
echo -e "  ACR:     ${ACR_LOGIN_SERVER}"
echo -e ""
echo -e "  To start local MCP servers (required for tool calls):"
echo -e "    ${CYAN}./start.sh --local-only${NC}"
echo -e ""
echo -e "  To view logs:"
echo -e "    ${CYAN}az containerapp logs show -n ${CONTAINER_APP_NAME} -g ${RESOURCE_GROUP} --type console${NC}"
echo -e "${GREEN}=============================================${NC}"
