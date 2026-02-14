<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

## Azure AI Foundry Multi-Agent System

This project is a Python-based multi-agent system that connects to Azure AI Foundry.

### Project Setup Completed

- [x] Verify that the copilot-instructions.md file in the .github directory is created.
- [x] Clarify Project Requirements - Python multi-agent system for Azure AI Foundry
- [x] Scaffold the Project - Created project structure with src/agents/, config, and dependencies
- [x] Customize the Project - Built multi-agent system with BaseAgent and SimpleAgent classes
- [x] Install Required Extensions - No extensions required
- [x] Compile the Project - Dependencies installed successfully
- [x] Create and Run Task - Not needed for this project type
- [x] Launch the Project - Ready to run with `python main.py` after configuration
- [x] Ensure Documentation is Complete - README.md created with setup instructions

### Key Files

- `main.py` - Entry point for the agent system
- `src/config.py` - Configuration management for Azure credentials
- `src/agents/base_agent.py` - Base class for all agents
- `src/agents/simple_agent.py` - Example agent implementation
- `.env.example` - Template for environment variables

### Setup Instructions

1. Copy `.env.example` to `.env` and add your Azure AI Foundry credentials
2. Activate virtual environment: `source .venv/bin/activate`
3. Run the agent: `python main.py`

### Development Guidelines

- Extend `BaseAgent` class to create custom agents
- Use the config module for managing Azure credentials
- Follow the async/await pattern for agent processing
- Add new agents in the `src/agents/` directory
