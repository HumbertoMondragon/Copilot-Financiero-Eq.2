# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Copilot Financiero Eq.2** — A Python-based AI financial copilot powered by the Anthropic Claude API.

## Setup

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies (once requirements.txt or pyproject.toml is created)
pip install -r requirements.txt
```

Environment variables are loaded from `.env`. The required variable is:
- `ANTHROPIC_API_KEY` — Anthropic API key for Claude integration

## Development Commands

_These will be defined as the project grows. Update this section when build/lint/test tooling is added._

```bash
# Run the app (entry point TBD)
python main.py

# Run tests (framework TBD)
pytest
```

## Architecture

This project is in its initial state. As the codebase develops, document the high-level architecture here:

- **Entry point** — `main.py` (to be created)
- **Claude API integration** — uses the `anthropic` Python SDK; load the client with the `ANTHROPIC_API_KEY` env var
- **Financial domain logic** — (to be defined)

When adding Claude API calls, prefer streaming responses for interactive copilot UX and include prompt caching for repeated system prompts to reduce latency and cost.
