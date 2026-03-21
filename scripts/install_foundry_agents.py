#!/usr/bin/env python3
"""Install NextGen agents into Azure AI Foundry as named agents.

Follows the Springfield Core Team pattern: create versioned agents in Foundry
so they can be called via the Responses API with agent_reference.

Usage:
    python scripts/install_foundry_agents.py              # install all agents
    python scripts/install_foundry_agents.py --list        # show what would be installed
    python scripts/install_foundry_agents.py --agent belle # install one agent
    python scripts/install_foundry_agents.py --verify      # verify installed agents

Requires:
    - FOUNDRY_PROJECT_ENDPOINT or PROJECT_ENDPOINT env var
    - azure-ai-projects SDK
    - DefaultAzureCredential (managed identity or az login)
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config
from src.agents.system_prompts import (
    SMEE_ORCHESTRATOR_PROMPT,
    BELLE_ANALYZER_PROMPT,
    GASTON_EVALUATOR_PROMPT,
    RAPHUNZEL_GRADES_PROMPT,
    TIANA_APPLICATION_PROMPT,
    MULAN_RECOMMENDATION_PROMPT,
    MERLIN_EVAL_PROMPT,
    MIRABEL_VIDEO_PROMPT,
    PRESENTER_PROMPT,
)

# Agent registry: name → (model_tier, system_prompt, description)
AGENT_REGISTRY = {
    "smee": {
        "model": config.model_tier_orchestrator,
        "prompt": SMEE_ORCHESTRATOR_PROMPT,
        "description": "Pipeline Orchestrator — coordinates all agents in the evaluation workflow",
    },
    "belle": {
        "model": config.model_tier_workhorse,
        "prompt": BELLE_ANALYZER_PROMPT,
        "description": "Document Intelligence — PDF/DOCX parsing, section detection, OCR",
    },
    "tiana": {
        "model": config.model_tier_workhorse,
        "prompt": TIANA_APPLICATION_PROMPT,
        "description": "Application Reader — essay and application text analysis",
    },
    "rapunzel": {
        "model": config.model_tier_premium,
        "prompt": RAPHUNZEL_GRADES_PROMPT,
        "description": "Grade Analyst — transcript parsing and academic record analysis",
    },
    "mulan": {
        "model": config.model_tier_workhorse,
        "prompt": MULAN_RECOMMENDATION_PROMPT,
        "description": "Recommendation Analyst — recommendation letter analysis",
    },
    "merlin": {
        "model": config.model_tier_merlin,
        "prompt": MERLIN_EVAL_PROMPT,
        "description": "Synthesis Evaluator — final comprehensive evaluation",
    },
    "gaston": {
        "model": config.model_tier_reasoning,
        "prompt": GASTON_EVALUATOR_PROMPT,
        "description": "Counter-Evaluator — consistency audit, bias check, quality gate",
    },
    "aurora": {
        "model": config.model_tier_workhorse,
        "prompt": PRESENTER_PROMPT,
        "description": "Report Formatter — executive summary and presentation",
    },
    "mirabel": {
        "model": config.foundry_vision_model_name or "gpt-4o",
        "prompt": MIRABEL_VIDEO_PROMPT,
        "description": "Video Analyst — video submission frame and audio analysis",
    },
}


def get_project_client():
    """Get an AIProjectClient for the configured Foundry endpoint."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = (
        config.foundry_project_endpoint
        or os.getenv("PROJECT_ENDPOINT")
        or os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    )
    if not endpoint:
        print("ERROR: No Foundry project endpoint configured.")
        print("  Set FOUNDRY_PROJECT_ENDPOINT or PROJECT_ENDPOINT env var.")
        sys.exit(1)

    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)
    print(f"Connected to Foundry: {endpoint[:60]}...")
    return client


def install_agent(project, name: str, agent_def: dict, dry_run: bool = False):
    """Create or update a single agent in Foundry."""
    from azure.ai.projects.models import PromptAgentDefinition

    model = agent_def["model"]
    prompt = agent_def["prompt"]
    description = agent_def["description"]

    slug = f"nextgen-{name}"
    print(f"  {'[DRY RUN] ' if dry_run else ''}Installing {slug} (model={model})")

    if dry_run:
        print(f"    → {description}")
        print(f"    → Prompt: {len(prompt)} chars")
        return None

    try:
        agent = project.agents.create_version(
            agent_name=slug,
            definition=PromptAgentDefinition(
                model=model,
                instructions=prompt,
                description=description,
            ),
        )
        print(f"    ✓ {slug} installed successfully")
        return agent
    except Exception as e:
        print(f"    ✗ {slug} FAILED: {e}")
        return None


def verify_agents(project):
    """Verify all agents are installed and responsive."""
    print("\nVerifying installed agents...")
    from azure.ai.projects.models import PromptAgentDefinition

    for name in AGENT_REGISTRY:
        slug = f"nextgen-{name}"
        try:
            # Try to get the agent by listing and matching
            agents = project.agents.list_agents()
            found = False
            for a in agents:
                if getattr(a, 'name', '') == slug:
                    found = True
                    print(f"  ✓ {slug} — found (model={getattr(a, 'model', 'unknown')})")
                    break
            if not found:
                print(f"  ✗ {slug} — NOT FOUND")
        except Exception as e:
            print(f"  ? {slug} — could not verify: {e}")


def main():
    parser = argparse.ArgumentParser(description="Install NextGen agents into Azure AI Foundry")
    parser.add_argument("--list", action="store_true", help="Show what would be installed")
    parser.add_argument("--agent", type=str, help="Install a single agent by name")
    parser.add_argument("--verify", action="store_true", help="Verify installed agents")
    args = parser.parse_args()

    if args.list:
        print("NextGen Agent Registry:")
        print("=" * 70)
        for name, defn in AGENT_REGISTRY.items():
            print(f"  nextgen-{name:<12} model={defn['model']:<20} {defn['description'][:50]}")
        print(f"\nTotal: {len(AGENT_REGISTRY)} agents")
        return

    project = get_project_client()

    if args.verify:
        verify_agents(project)
        return

    if args.agent:
        if args.agent not in AGENT_REGISTRY:
            print(f"Unknown agent: {args.agent}")
            print(f"Available: {', '.join(AGENT_REGISTRY.keys())}")
            sys.exit(1)
        install_agent(project, args.agent, AGENT_REGISTRY[args.agent])
    else:
        print(f"Installing {len(AGENT_REGISTRY)} agents into Foundry...")
        print("=" * 50)
        installed = 0
        for name, defn in AGENT_REGISTRY.items():
            result = install_agent(project, name, defn)
            if result is not None:
                installed += 1
        print(f"\n{'=' * 50}")
        print(f"Installed: {installed}/{len(AGENT_REGISTRY)} agents")
        if installed == len(AGENT_REGISTRY):
            print("\n✓ All agents installed. They can now be called via:")
            print('  openai.responses.create(extra_body={"agent_reference": {"name": "nextgen-belle", "type": "agent_reference"}}, ...)')


if __name__ == "__main__":
    main()
