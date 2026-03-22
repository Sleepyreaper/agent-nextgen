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
import importlib.util
import os
import sys
from pathlib import Path

# Ensure repo root is importable
REPO_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

# Import system_prompts directly to avoid __init__.py pulling in heavy deps
_sp_spec = importlib.util.spec_from_file_location(
    "system_prompts",
    os.path.join(REPO_ROOT, "src", "agents", "system_prompts.py"),
)
_sp = importlib.util.module_from_spec(_sp_spec)
_sp_spec.loader.exec_module(_sp)

SMEE_ORCHESTRATOR_PROMPT = _sp.SMEE_ORCHESTRATOR_PROMPT
BELLE_ANALYZER_PROMPT = _sp.BELLE_ANALYZER_PROMPT
GASTON_EVALUATOR_PROMPT = _sp.GASTON_EVALUATOR_PROMPT
RAPHUNZEL_GRADES_PROMPT = _sp.RAPHUNZEL_GRADES_PROMPT
TIANA_APPLICATION_PROMPT = _sp.TIANA_APPLICATION_PROMPT
MULAN_RECOMMENDATION_PROMPT = _sp.MULAN_RECOMMENDATION_PROMPT
MERLIN_EVAL_PROMPT = _sp.MERLIN_EVAL_PROMPT
MIRABEL_VIDEO_PROMPT = _sp.MIRABEL_VIDEO_PROMPT
PRESENTER_PROMPT = _sp.PRESENTER_PROMPT

# Agents whose prompts live in their class files (not system_prompts.py)
# Import the class-level prompt builders
_moana_spec = importlib.util.spec_from_file_location(
    "moana_school_context",
    os.path.join(REPO_ROOT, "src", "agents", "moana_school_context.py"),
)
_naveen_spec = importlib.util.spec_from_file_location(
    "naveen_school_data_scientist",
    os.path.join(REPO_ROOT, "src", "agents", "naveen_school_data_scientist.py"),
)
_pocahontas_spec = importlib.util.spec_from_file_location(
    "pocahontas_cohort_analyst",
    os.path.join(REPO_ROOT, "src", "agents", "pocahontas_cohort_analyst.py"),
)

# Inline prompts for agents that build prompts in __init__
# These are condensed versions of the class-level _build_system_prompt() output
MOANA_PROMPT = """You are Moana, Student School Context Analyzer for NextGen evaluation.

Your mission: Build rich contextual narratives about each student's school environment
using NCES data. You answer the key question: "What did this student's world look like?"

Key insight: A 4.0 GPA from a school with 2 AP classes and 70% free lunch
is categorically different from the same GPA at a school with 20 APs and 15% free lunch.
Context defines opportunity.

You analyze:
- What did this school offer? (programs, resources, demographics)
- What did the student do with what was available? (course selection, rigor)
- How should their achievements be interpreted in context?
- Are there equity factors that make their record more impressive?

Output a structured JSON with: school_narrative, opportunity_landscape,
student_utilization_assessment, and contextual_interpretation."""

NAVEEN_PROMPT = """You are Naveen, School Data Scientist for NextGen evaluation.

Your role: Analyze school-level NCES data to produce component scores that quantify
each school's resource level.

Component scores (each 0-100):
- academic_resources: AP/IB courses, advanced programs, college prep
- financial_resources: per-pupil expenditure, Title I status, funding
- student_support: counselor ratio, teacher ratio, extracurriculars
- demographic_context: free/reduced lunch %, diversity, community factors
- overall_score: weighted composite (Academic 30%, Financial 25%, Support 25%, Demographic 20%)

IMPORTANT: A LOW score means the school is UNDER-RESOURCED. This is NOT a quality
judgment. An under-resourced school producing high-achieving students is evidence
of exceptional student and teacher effort.

Output structured JSON with all component scores, confidence levels, and evidence."""

POCAHONTAS_PROMPT = """You are Pocahontas, Cohort Equity Analyst for NextGen evaluation.

Your mission: Ensure students from under-resourced schools are evaluated fairly by
accounting for opportunities they did and did NOT have access to.

Equity Tier Definitions:
- Tier 1 (Highest Need): >75% FRL, minimal AP/honors. Multiplier: 1.15-1.25
- Tier 2 (High Need): 50-75% FRL, few AP/honors. Multiplier: 1.08-1.15
- Tier 3 (Moderate): 25-50% FRL, some AP/honors. Multiplier: 1.00-1.08
- Tier 4 (Well-Resourced): <25% FRL, good AP selection. Multiplier: 0.95-1.00
- Tier 5 (Highly Resourced): <10% FRL, extensive AP/IB. Multiplier: 0.90-0.95

Context multipliers are NOT penalties. They are corrections.
A 3.8 GPA at a Tier 1 school with no AP courses demonstrates MORE
than a 3.8 at a Tier 5 school with extensive AP weighting.

Output JSON with: equity_tier, context_multiplier, opportunity_utilization_score,
diamond_in_rough_flag, and narrative explanation."""

MILO_PROMPT = """You are Milo Thatch, Data Scientist for NextGen evaluation.

Your role: Apply data science analysis to scholarship evaluation. You analyze patterns
across applicants, validate scoring consistency, and provide ML-informed insights.

You perform:
- Score normalization and consistency checks across agents
- Pattern analysis: how does this applicant compare to the training cohort?
- Feature importance: which factors are driving the evaluation?
- Confidence intervals on overall scores
- Alignment analysis: does the AI evaluation align with historical committee decisions?

Output structured JSON with: normalized_scores, alignment_analysis,
confidence_metrics, and data_science_insights."""

BASHFUL_PROMPT = """You are Bashful, the Summarizer for NextGen evaluation.

Your role: Create concise, accurate summaries of agent outputs. You distill
verbose agent analyses into clear, actionable summaries for the committee.

Rules:
- Be concise but complete — capture key findings, not filler
- Preserve critical details: scores, flags, concerns
- Use plain language accessible to non-technical reviewers
- Never embellish or add interpretation beyond what agents reported

Output a structured summary with key findings from each agent."""

# Model tier defaults — can be overridden via env vars
_ORCHESTRATOR = os.getenv("MODEL_TIER_ORCHESTRATOR", "o3")
_REASONING = os.getenv("MODEL_TIER_REASONING", "o3")
_PREMIUM = os.getenv("MODEL_TIER_PREMIUM", "gpt-5.4-pro")
_MERLIN = os.getenv("MODEL_TIER_MERLIN", "gpt-5.4-pro")
_WORKHORSE = os.getenv("MODEL_TIER_WORKHORSE", "gpt-5.4")
_VISION = os.getenv("FOUNDRY_VISION_MODEL_NAME", "gpt-5.4")

# Agent registry: name → (model, system_prompt, description)
AGENT_REGISTRY = {
    "smee": {
        "model": _ORCHESTRATOR,
        "prompt": SMEE_ORCHESTRATOR_PROMPT,
        "description": "Pipeline Orchestrator — coordinates all agents in the evaluation workflow",
    },
    "belle": {
        "model": _WORKHORSE,
        "prompt": BELLE_ANALYZER_PROMPT,
        "description": "Document Intelligence — PDF/DOCX parsing, section detection, OCR",
    },
    "tiana": {
        "model": _WORKHORSE,
        "prompt": TIANA_APPLICATION_PROMPT,
        "description": "Application Reader — essay and application text analysis",
    },
    "rapunzel": {
        "model": _PREMIUM,
        "prompt": RAPHUNZEL_GRADES_PROMPT,
        "description": "Grade Analyst — transcript parsing and academic record analysis",
    },
    "mulan": {
        "model": _WORKHORSE,
        "prompt": MULAN_RECOMMENDATION_PROMPT,
        "description": "Recommendation Analyst — recommendation letter analysis",
    },
    "merlin": {
        "model": _MERLIN,
        "prompt": MERLIN_EVAL_PROMPT,
        "description": "Synthesis Evaluator — final comprehensive evaluation",
    },
    "gaston": {
        "model": _REASONING,
        "prompt": GASTON_EVALUATOR_PROMPT,
        "description": "Counter-Evaluator — consistency audit, bias check, quality gate",
    },
    "aurora": {
        "model": _WORKHORSE,
        "prompt": PRESENTER_PROMPT,
        "description": "Report Formatter — executive summary and presentation",
    },
    "mirabel": {
        "model": _VISION,
        "prompt": MIRABEL_VIDEO_PROMPT,
        "description": "Video Analyst — video submission frame and audio analysis",
    },
    "moana": {
        "model": _WORKHORSE,
        "prompt": MOANA_PROMPT,
        "description": "School Context Analyst — contextualizes student achievements within school environment",
    },
    "naveen": {
        "model": _WORKHORSE,
        "prompt": NAVEEN_PROMPT,
        "description": "School Data Scientist — NCES data evaluation and component scoring",
    },
    "pocahontas": {
        "model": _WORKHORSE,
        "prompt": POCAHONTAS_PROMPT,
        "description": "Cohort Equity Analyst — equity tiers, context multipliers, diamond detection",
    },
    "milo": {
        "model": _PREMIUM,
        "prompt": MILO_PROMPT,
        "description": "Data Scientist — ML analysis, score normalization, alignment validation",
    },
    "bashful": {
        "model": _WORKHORSE,
        "prompt": BASHFUL_PROMPT,
        "description": "Summarizer — concise agent output summaries for committee review",
    },
}


def get_project_client():
    """Get an AIProjectClient for the configured Foundry endpoint."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = (
        os.getenv("PROJECT_ENDPOINT")
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
            ),
            description=description,
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
            agents = list(project.agents.list())
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
