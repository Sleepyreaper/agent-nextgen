"""Main entry point for the Azure AI Foundry agent system."""

import asyncio
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import config
from src.agents import BashfulAgent


async def main():
    """Main function to run the agent system."""
    
    # Validate configuration
    if not config.validate():
        missing = config.get_missing_config()
        print("❌ Missing required configuration:")
        for item in missing:
            print(f"   - {item}")
        print("\nPlease set these values in your .env file.")
        print("See .env.example for reference.")
        return
    
    print("✅ Configuration validated")
    
    # Initialize client
    try:
        if config.azure_openai_endpoint:
            print("🔗 Connecting to Azure OpenAI...")
            
            # Use API key if provided, otherwise use DefaultAzureCredential
            if config.azure_openai_api_key:
                client = AzureOpenAI(
                    api_key=config.azure_openai_api_key,
                    api_version=config.api_version,
                    azure_endpoint=config.azure_openai_endpoint
                )
            else:
                # Use DefaultAzureCredential for authentication
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    "https://cognitiveservices.azure.com/.default"
                )
                client = AzureOpenAI(
                    azure_ad_token_provider=token_provider,
                    api_version=config.api_version,
                    azure_endpoint=config.azure_openai_endpoint
                )
            
            print("✅ Connected to Azure OpenAI")
        else:
            # Fallback to AI Foundry if configured
            from azure.ai.projects import AIProjectClient
            
            if config.connection_string:
                print("🔗 Connecting to Azure AI Foundry using connection string...")
                client = AIProjectClient.from_connection_string(
                    credential=DefaultAzureCredential(),
                    conn_str=config.connection_string
                )
            else:
                print("🔗 Connecting to Azure AI Foundry...")
                client = AIProjectClient(
                    credential=DefaultAzureCredential(),
                    subscription_id=config.subscription_id,
                    resource_group_name=config.resource_group,
                    project_name=config.project_name
                )
            
            print("✅ Connected to Azure AI Foundry")
        
        # Create a Bashful agent
        agent = BashfulAgent(
            name="Assistant",
            client=client,
            system_prompt="You are a helpful AI assistant.",
            model=config.deployment_name
        )
        
        print(f"\n🤖 Agent '{agent.name}' is ready!")
        print("Type 'exit' or 'quit' to end the conversation.\n")
        
        # Simple conversation loop
        while True:
            user_input = input("You: ").strip()
            
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            response = await agent.process(user_input)
            print(f"{agent.name}: {response}\n")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("\nPlease check your Azure AI Foundry configuration and credentials.")


if __name__ == "__main__":
    asyncio.run(main())
