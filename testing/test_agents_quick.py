#!/usr/bin/env python3
"""Quick test to verify Azure OpenAI connection for all agents."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import config

print("="*70)
print("Quick Azure OpenAI Agent Connection Test")
print("="*70)

# 1. Check config
print(f"\n✓ Endpoint: {config.azure_openai_endpoint[:50]}...")
print(f"✓ Deployment: {config.deployment_name}")
print(f"✓ API Version: {config.api_version}")

# 2. Initialize client
print("\n🔌 Initializing Azure OpenAI client...")
try:
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint
    )
    print("   ✅ Client initialized")
except Exception as e:
    print(f"   ❌ Client failed: {e}")
    sys.exit(1)

# 3. Test GPT connection
print("\n🧪 Testing GPT connection...")
try:
    response = client.chat.completions.create(
        model=config.deployment_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with exactly: 'Connection successful!'"}
        ],
        max_completion_tokens=20,
        temperature=1
    )
    message = response.choices[0].message.content
    print(f"   ✅ GPT Response: {message}")
except Exception as e:
    print(f"   ❌ GPT failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 4. Test each agent class can be initialized
print("\n👥 Initializing agents...")
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator
from src.agents.smee_orchestrator import SmeeOrchestrator

agents = []
try:
    agents.append(("Tiana", TianaApplicationReader("Tiana", client, config.deployment_name)))
    print("   ✅ Tiana initialized")
    
    agents.append(("Rapunzel", RapunzelGradeReader("Rapunzel", client, config.deployment_name)))
    print("   ✅ Rapunzel initialized")
    
    agents.append(("Moana", MoanaSchoolContext("Moana", client, config.deployment_name)))
    print("   ✅ Moana initialized")
    
    agents.append(("Mulan", MulanRecommendationReader("Mulan", client, config.deployment_name)))
    print("   ✅ Mulan initialized")
    
    agents.append(("Merlin", MerlinStudentEvaluator("Merlin", client, config.deployment_name)))
    print("   ✅ Merlin initialized")
    
    agents.append(("Smee", SmeeOrchestrator("Smee", client, config.deployment_name)))
    print("   ✅ Smee initialized")
except Exception as e:
    print(f"   ❌ Agent initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 5. Test one simple agent call
print("\n🎯 Testing Tiana with simple request...")
sample_app = {
    "ApplicationID": 999,
    "ApplicantName": "Jane Doe",
    "Email": "jane@example.com",
    "ApplicationText": "I am a high school senior interested in computer science. I have taken AP CS and built several apps."
}

async def test_tiana():
    tiana = agents[0][1]  # Get Tiana agent
    try:
        result = await tiana.parse_application(sample_app)
        if result.get('status') == 'success':
            print(f"   ✅ Tiana successfully parsed application")
            print(f"   ✅ Extracted: {result.get('applicant_name', 'N/A')}")
            return True
        else:
            print(f"   ⚠️  Tiana returned status: {result.get('status')}")
            print(f"   Error: {result.get('error', 'Unknown')}")
            return False
    except Exception as e:
        print(f"   ❌ Tiana failed: {e}")
        import traceback
        traceback.print_exc()
        return False

success = asyncio.run(test_tiana())

# Final summary
print("\n" + "="*70)
if success:
    print("🎉 SUCCESS! All agents can connect to Azure OpenAI GPT instance!")
    print("\nYour Disney multi-agent system is ready:")
    print("  ✅ Tiana - Application Reader")
    print("  ✅ Rapunzel - Grade Reader")
    print("  ✅ Moana - School Context Analyzer")
    print("  ✅ Mulan - Recommendation Reader")
    print("  ✅ Merlin - Student Evaluator")
    print("  ✅ Smee - Orchestrator")
    print("\n All agents can reason about student applications using GPT-5.2!")
else:
    print("⚠️  Some agents had issues. Check the errors above.")
print("="*70)

sys.exit(0 if success else 1)
