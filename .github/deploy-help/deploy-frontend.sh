# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
#!/usr/bin/env bash

set -ux # uncomment this line to debug

# Variables
#RESOURCE_GROUP="<rg>" # same rg as your backend graphrag deployment
#LOCATION="<region>" # region of your deployment
#ALLOW_IP="<your public IP address so you can access the ACA>"
#APIM_SUBSCRIPTION_KEY="<APIM SUBSCRIPTION KEY FROM PORTAL>"

scriptDir=`pwd` # run in the infra directory

populateRequiredParams () {
    local paramsFile=$1
    printf "Checking required parameters... "
    checkRequiredParams $paramsFile
    # The jq command below sets environment variable based on the key-value
    # pairs in a JSON-formatted file
    eval $(jq -r 'to_entries | .[] | "export \(.key)=\(.value)"' $paramsFile)
    printf "Done.\n"
}

# Check if the correct number of arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <graphrag deploy params file> <frontend params file>"
    exit 1
fi

DEPLOY_PARAMS_FILE=$1
DEPLOY_FRONTEND_PARAMS_FILE=$2

populateRequiredParams $DEPLOY_PARAMS_FILE
populateRequiredParams $DEPLOY_FRONTEND_PARAMS_FILE

ENVIRONMENT_NAME="graphrag-aca-env" # will be created for you
CONTAINER_APP_NAME="graphrag-frontend" # will be created for you
CONTAINER_NAME="graphrag:frontend" # Default but you should be able to name it anything


REGISTRY_SERVER="$(az acr list --resource-group $RESOURCE_GROUP --query "[0].loginServer" -o tsv)"
REGISTRY_USERNAME="$(az acr list --resource-group $RESOURCE_GROUP --query "[0].name" -o tsv)"
REGISTRY_PASSWORD="$(az acr credential show --name $REGISTRY_USERNAME --resource-group $RESOURCE_GROUP  --query "passwords[0].value" -o tsv)"
CONTAINER_IMAGE="$REGISTRY_SERVER/$CONTAINER_NAME"

APIM_NAME="$(az apim list --resource-group $RESOURCE_GROUP --query "[0].name" -o tsv)"
DEPLOYMENT_URL="$(az apim list --resource-group $RESOURCE_GROUP --query "[0].gatewayUrl" -o tsv)"

LAW_NAME="$(az monitor log-analytics workspace list --resource-group $RESOURCE_GROUP --query "[0].name" -o tsv)"
LAW_ID="$(az monitor log-analytics workspace list --resource-group $RESOURCE_GROUP --query "[0].customerId" -o tsv)"
LAW_KEY="$(az monitor log-analytics workspace get-shared-keys --resource-group $RESOURCE_GROUP --workspace-name $LAW_NAME --query primarySharedKey --output tsv)"

# Deploy frontend image
az acr build --only-show-errors \
  --registry $REGISTRY_SERVER \
  --file $scriptDir/../docker/Dockerfile-frontend \
  --image $CONTAINER_IMAGE \
  $scriptDir/../


# Create an environment for the Container App
az containerapp env create \
  --name $ENVIRONMENT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --logs-destination log-analytics \
  --logs-workspace-id $LAW_ID \
  --logs-workspace-key $LAW_KEY

# Deploy the Container App
az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --environment $ENVIRONMENT_NAME \
  --image $CONTAINER_IMAGE \
  --registry-server $REGISTRY_SERVER \
  --registry-username $REGISTRY_USERNAME \
  --registry-password $REGISTRY_PASSWORD \
  --env-vars DEPLOYMENT_URL=$DEPLOYMENT_URL APIM_SUBSCRIPTION_KEY=$APIM_SUBSCRIPTION_KEY

# Allow ingress
az containerapp ingress enable \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --type external --target-port 0 --transport auto

# Update Ingress to let me have access
az containerapp ingress access-restriction set \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --rule-name allowSpecificIP --ip-address $ALLOW_IP --action Allow

# Print out the URL for the Container App
echo "https://"$(az containerapp show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn --output tsv)
