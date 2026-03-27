# README Redesign — Design Document

## Goal

Redesign ClawForge's README into a professional English-language showcase. Add Russian translations. Translate ARCHITECTURE.md to English.

## Context

ClawForge serves dual purpose: real product (AI agent factory on OpenClaw) and portfolio/showcase project (built as a job assignment, demonstrating architectural thinking). The README must impress in 30 seconds while providing enough depth for those who want to explore further.

## Decisions

### Positioning
- **"Built on OpenClaw"** — neutral, like "Built on Kubernetes". No percentage splits (was "95%/5%")
- **"ClawForge = orchestration brain, OpenClaw = runtime"** — clear separation of concerns
- Tagline: **"Self-expanding AI agent factory built on OpenClaw"**

### Structure (Approach A: Product-first with example)
1. Badges (Python 3.10+, Platform Linux, Built on OpenClaw)
2. `# ClawForge` + one-liner + one paragraph
3. `## Architecture` — mermaid flowchart (ClawForge orchestration ↔ OpenClaw runtime)
4. `## What It Does` — 5 bullet features (pipeline, self-expansion, per-bot, automations, delegation)
5. `## How It Works` — pipeline stages table + strategies table + compact example dialog
6. `## Tech Stack` — table
7. `## Getting Started` — streamlined install steps
8. `## Commands` — table with natural language note
9. `## Documentation` — link to ARCHITECTURE.md

### Visual
- **Mermaid diagrams** (GitHub renders natively, looks professional)
- **Badges** in header (real ones only, no fake "build passing")
- No ASCII art

### Languages
- **README.md** — English (primary)
- **README_RU.md** — Russian translation, in repo root
- Cross-links in header: `[English](README.md) · [Русский](README_RU.md)`
- **docs/ARCHITECTURE.md** — translate to English
- **docs/ARCHITECTURE_RU.md** — current Russian version, renamed

### Target length
~150 lines for README (middle-ground: enough to impress, not so long it's skipped)

## Files to create/modify

| File | Action |
|------|--------|
| `README.md` | Full rewrite → English, new structure |
| `README_RU.md` | New file — Russian translation of README.md |
| `docs/ARCHITECTURE.md` | Translate to English |
| `docs/ARCHITECTURE_RU.md` | Rename current Russian version |

## Out of scope
- LICENSE file (none exists, not adding)
- CI/CD badges (no CI configured)
- ARCHITECTURE.md content changes (translation only, no restructuring)
