import os
import asyncio
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

async def list_old_api_agents():
    endpoint = os.getenv("PROJECT_ENDPOINT")
    
    # Try using the OLD agents API
    async with DefaultAzureCredential() as credential:
        async with AgentsClient(endpoint=endpoint, credential=credential) as client:
            print(f"Checking for agents using OLD API at: {endpoint}\n")
            
            try:
                agents = client.list_agents()
                print("Found agents:")
                async for agent in agents:
                    print(f"  ID: {agent.id}")
                    print(f"  Name: {agent.name if hasattr(agent, 'name') else 'N/A'}")
                    print()
            except Exception as e:
                print(f"Error: {e}")

asyncio.run(list_old_api_agents())
