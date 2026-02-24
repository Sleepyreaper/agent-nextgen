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
    # dump model provider info for debugging
    print(f"Model provider: {config.model_provider}")
    print(f"Azure deployment name: {config.deployment_name}")
    print(f"Foundry model name: {config.foundry_model_name}")
    
    # Initialize client based on provider hint
    try:
        if config.model_provider and config.model_provider.lower() == "foundry":
            print("🔗 Model provider is Foundry; creating Foundry client...")
            from src.agents.foundry_client import FoundryClient
            client = FoundryClient(
                endpoint=config.foundry_project_endpoint,
                api_key=config.foundry_api_key
            )
            print(f"✅ Connected to Foundry endpoint: {config.foundry_project_endpoint}")
        else:
            # default to Azure OpenAI
            print("🔗 Connecting to Azure OpenAI...")
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
            print("✅ Connected to Azure OpenAI")

        # Import core agents
        from src.agents import (
            SmeeOrchestrator,
            BelleDocumentAnalyzer,
            TianaApplicationReader,
            MulanRecommendationReader,
            MoanaSchoolContext,
            RapunzelGradeReader,
            MerlinStudentEvaluator
        )

        # Instantiate agents
        smee = SmeeOrchestrator("Smee", client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        belle = BelleDocumentAnalyzer(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        tiana = TianaApplicationReader(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        mulan = MulanRecommendationReader(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        moana = MoanaSchoolContext(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        rapunzel = RapunzelGradeReader(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))
        merlin = MerlinStudentEvaluator(client=client, model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name))

        # Register agents with Smee
        smee.register_agent("belle", belle)
        smee.register_agent("application_reader", tiana)
        smee.register_agent("recommendation_reader", mulan)
        smee.register_agent("school_context", moana)
        smee.register_agent("grade_reader", rapunzel)
        smee.register_agent("student_evaluator", merlin)

        print("\n🤖 Smee orchestrator and core agents are ready!")
        print("Agents: belle, tiana, mulan, moana, rapunzel, merlin")
        print("Type 'exit' or 'quit' to end the session.\n")

        # Example: orchestrate a workflow (replace with real application data as needed)
        while True:
            user_input = input("Enter application JSON or 'exit': ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if not user_input:
                continue
            try:
                application = json.loads(user_input)
            except Exception as e:
                print(f"Invalid JSON: {e}")
                continue
            # Define the agent execution order
            evaluation_steps = [
                "belle",
                "application_reader",
                "recommendation_reader",
                "school_context",
                "grade_reader",
                "data_scientist",
                "student_evaluator"
            ]
            results = await smee.coordinate_evaluation(application, evaluation_steps)
            print("\n=== Evaluation Results ===")
            print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("\nPlease check your Azure AI Foundry configuration and credentials.")


if __name__ == "__main__":
    asyncio.run(main())
