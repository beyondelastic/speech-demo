// =============================================================================
// OR Voice Assistant — Azure Container Apps Infrastructure
//
// Deploys:
//   - Azure Container Registry (ACR)
//   - Container Apps Environment (with Log Analytics)
//   - Container App (with system-assigned managed identity)
//
// After deployment, grant the managed identity 'Cognitive Services User' role
// on your AI Services resource (see deploy.sh).
//
// Usage:
//   az deployment group create \
//     --resource-group <rg> \
//     --template-file infra/main.bicep \
//     --parameters projectEndpoint=<endpoint> speechKey=<key>
// =============================================================================

@description('Location for all resources')
param location string = resourceGroup().location

@description('Base name for resources (used as prefix)')
param appName string = 'or-assistant'

@description('Foundry project endpoint URL')
param projectEndpoint string

@description('Azure Speech Service key')
@secure()
param speechKey string

@description('Speech region')
param speechRegion string = 'swedencentral'

@description('Foundry agent ID')
param agentId string = 'playwright-agent'

@description('Container image (set after first ACR build, leave empty for initial deploy)')
param containerImage string = ''

// --- Container Registry ---
var acrName = replace('${appName}acr${uniqueString(resourceGroup().id)}', '-', '')

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// --- Log Analytics Workspace ---
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${appName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// --- Container Apps Environment ---
resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${appName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// --- Container App ---
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${appName}-backend'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'speech-key'
          value: speechKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: '${appName}-backend'
          image: !empty(containerImage) ? containerImage : 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'PROJECT_ENDPOINT', value: projectEndpoint }
            { name: 'AGENT_ID', value: agentId }
            { name: 'SPEECH_KEY', secretRef: 'speech-key' }
            { name: 'SPEECH_REGION', value: speechRegion }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

// --- Outputs ---
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output containerAppName string = containerApp.name
output principalId string = containerApp.identity.principalId
