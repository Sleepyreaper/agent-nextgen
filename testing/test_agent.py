"""Test script for the Azure OpenAI agent."""

import asyncio
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import config
from src.agents import BashfulAgent


async def test_agent():
    """Run automated tests on the agent."""
    
    # Validate configuration
    if not config.validate():
        missing = config.get_missing_config()
        print("❌ Missing required configuration:")
        for item in missing:
            print(f"   - {item}")
        return
    
    print("✅ Configuration validated\n")
    
    # Initialize client
    try:
        if config.azure_openai_api_key:
            client = AzureOpenAI(
                api_key=config.azure_openai_api_key,
                api_version=config.api_version,
                azure_endpoint=config.azure_openai_endpoint
            )
        else:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default"
            )
            client = AzureOpenAI(
                azure_ad_token_provider=token_provider,
                api_version=config.api_version,
                azure_endpoint=config.azure_openai_endpoint
            )
        
        print("🔗 Connected to Azure OpenAI\n")
        
        # Create agent
        agent = BashfulAgent(
            name="TestAgent",
            client=client,
            system_prompt="You are a helpful AI assistant.",
            model=config.deployment_name
        )
        
        # Test messages
        test_messages = [
            "Hello! Can you hear me?",
            "What is 2 + 2?",
            "Write a very short haiku about AI"
        ]
        
        print("=" * 60)
        print("Running automated tests...")
        print("=" * 60 + "\n")
        
        for i, message in enumerate(test_messages, 1):
            print(f"Test {i}/{len(test_messages)}")
            print(f"You: {message}")
            
            try:
                response = await agent.process(message)
                print(f"{agent.name}: {response}\n")
                print("-" * 60 + "\n")
                
            except Exception as e:
                print(f"❌ Error: {str(e)}\n")
                print("-" * 60 + "\n")
        
        print("=" * 60)
        print("✅ All tests completed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Connection Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_agent())
