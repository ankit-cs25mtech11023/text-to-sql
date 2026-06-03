# CLAUDE.md — Project Instructions for Claude Code

## Project Overview

Text-to-SQL pipeline for Indian GST (Goods and Services Tax) data. Thesis project.
- Converts natural language questions → SQL → executes → shows results
- See `plan.md` for the full implementation plan and current status

## Key Rules

### Plan Maintenance
- **Always keep `plan.md` updated.** When a design decision changes, a phase is completed, or a new constraint is discovered — update plan.md in the same session.
- Mark completed phases with a `[DONE]` tag in the timeline table.
- If a new decision contradicts something in plan.md, update plan.md first, then implement.

### Git Workflow
- Repo: GitHub (remote will be set after creation)
- Commit after completing each meaningful unit of work (a file, a module, a fix)
- Commit messages: short, descriptive, prefixed with phase context (e.g., "phase1: add GST schema DDL")
- Never commit `.env`, `*.db`, or `__pycache__/`
- Push to remote after each session or major milestone

### Model Constraints
- **Deployment models must be ≤10B parameters** — future GPU can only handle this
- Primary: Llama 3.1-8B (Groq), Gemma2-9B (Groq)
- One 70B model (Llama 3.3-70B) is included ONLY as upper-bound baseline for thesis comparison
- All inference via Groq API for now; local GPU (vLLM) planned for Phase 6

### Code Style
- Python 3.11+ features are fine
- Type hints on all function signatures
- Use `pydantic` for config/settings validation
- Use `dataclasses` or `pydantic` for result types (PipelineResult, ExecutionResult, etc.)
- No comments unless the WHY is non-obvious
- Keep `core/` independent of Streamlit — it must be importable by FastAPI, eval scripts, etc.

### Database
- SQLite for now (demo/thesis). PostgreSQL in Phase 6.
- DB file: `database/gst_demo.db` (gitignored)
- Schema DDL in `database/schema.sql` — source of truth
- Column descriptions in `database/descriptions.json` — critical for LLM accuracy

### Environment
- Virtual env: `../SQL_venv` (outside Dev/, already exists)
- Secrets in `.env` (gitignored), template in `.env.example`
- Activate: `source ../SQL_venv/bin/activate`

## Current Status

**Phase:** Not started — beginning Phase 1 (Database Setup)

## File Map (key files)

| File | Purpose |
|------|---------|
| `plan.md` | Full implementation plan — keep updated |
| `config/settings.py` | Central config: model, DB path, API keys |
| `config/prompts.py` | All LLM prompt templates |
| `database/schema.sql` | GST table DDL (source of truth) |
| `database/descriptions.json` | Column descriptions for LLM context |
| `database/seed_data.py` | Generates synthetic GST data |
| `database/connection.py` | SQLAlchemy engine factory |
| `core/pipeline.py` | End-to-end orchestrator |
| `core/llm_client.py` | Abstract LLM + GroqClient |
| `core/self_correction.py` | Error feedback loop |
| `ui/app.py` | Streamlit chat interface |
| `evaluation/benchmark.py` | Batch evaluation runner |

## Session Checklist

At the start of each session:
1. Read `plan.md` to understand current state
2. Check `CLAUDE.md` current status section
3. Check git log for recent changes

Before ending a session:
1. Commit all changes with descriptive messages
2. Push to GitHub
3. Update the "Current Status" section above with what was done and what's next
