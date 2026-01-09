"""List all agents in the Azure AI Foundry project"""
import os
import asyncio
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

async def list_agents():
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    
    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=project_endpoint,
            credential=credential
        ) as project_client:
            print(f"Project endpoint: {project_endpoint}\n")
            print("Listing agents...")
            
            try:
                # List agents using the new API (returns async iterator)
                agents_list = project_client.agents.list()
                
                print(f"\nFound agents:\n")
                
                # Iterate through the async iterator
                async for agent in agents_list:
                    print(f"  ID: {agent.id}")
                    print(f"  Name: {agent.name}")
                    if hasattr(agent, 'model'):
                        print(f"  Model: {agent.model}")
                    if hasattr(agent, 'version'):
                        print(f"  Version: {agent.version}")
                    if hasattr(agent, 'description') and agent.description:
                        print(f"  Description: {agent.description}")
                    print()
                        
            except Exception as e:
                print(f"Error listing agents: {e}")
                print(f"Error type: {type(e)}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(list_agents())
