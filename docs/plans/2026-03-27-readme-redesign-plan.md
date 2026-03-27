# README Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite README.md in English as a professional showcase, add Russian version, translate ARCHITECTURE.md.

**Architecture:** 4 files to produce. README.md is written from scratch based on approved design. README_RU.md is a translation. ARCHITECTURE.md is translated from current Russian version. ARCHITECTURE_RU.md is the current file renamed.

**Tech Stack:** Markdown, Mermaid diagrams

**Design doc:** `docs/plans/2026-03-27-readme-redesign-design.md`

---

### Task 1: Rename ARCHITECTURE.md → ARCHITECTURE_RU.md

**Files:**
- Rename: `docs/ARCHITECTURE.md` → `docs/ARCHITECTURE_RU.md`

**Step 1: Rename the file**

```bash
git mv docs/ARCHITECTURE.md docs/ARCHITECTURE_RU.md
```

**Step 2: Add language cross-link at top of ARCHITECTURE_RU.md**

Add as first line:
```markdown
[English](ARCHITECTURE.md) · **Русский**
```

**Step 3: Commit**

```bash
git add docs/ARCHITECTURE_RU.md
git commit -m "docs: rename ARCHITECTURE.md to ARCHITECTURE_RU.md"
```

---

### Task 2: Create docs/ARCHITECTURE.md (English translation)

**Files:**
- Create: `docs/ARCHITECTURE.md`
- Reference: `docs/ARCHITECTURE_RU.md` (source for translation)

**Step 1: Translate ARCHITECTURE_RU.md to English**

Full translation of all sections. Preserve:
- All code blocks and JSON examples unchanged
- All table structures
- All file paths
- Mermaid/ASCII diagrams (translate labels only)

Add as first line:
```markdown
**English** · [Русский](ARCHITECTURE_RU.md)
```

**Step 2: Verify cross-links work**

Check that both files link to each other correctly.

**Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: add English translation of ARCHITECTURE.md"
```

---

### Task 3: Create README.md (English, full rewrite)

**Files:**
- Rewrite: `README.md`

**Step 1: Write the new README.md**

Structure (from approved design):

1. Language switcher: `**English** · [Русский](README_RU.md)`
2. Badges: Python 3.10+, Platform Linux, Built on OpenClaw
3. `# ClawForge` + tagline "Self-expanding AI agent factory built on OpenClaw"
4. One paragraph description
5. `## Architecture` — mermaid flowchart with two subgraphs (ClawForge orchestration, OpenClaw runtime)
6. `## What It Does` — 5 bullet features
7. `## How It Works` — pipeline stages table + strategies table + example dialog
8. `## Tech Stack` — table
9. `## Getting Started` — streamlined install
10. `## Commands` — table
11. `## Documentation` — link to docs/ARCHITECTURE.md

Source content: current README.md (for install steps, commands, example) + design doc for structure.

**Step 2: Verify mermaid renders**

Check mermaid syntax is valid (proper subgraph nesting, node definitions, arrow syntax).

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README.md in English with new structure"
```

---

### Task 4: Create README_RU.md (Russian translation)

**Files:**
- Create: `README_RU.md`
- Reference: `README.md` (source for translation)

**Step 1: Translate README.md to Russian**

Full translation. Preserve:
- All code blocks unchanged
- All mermaid diagram structure (translate labels)
- All badge URLs unchanged
- All file paths unchanged

Language switcher:
```markdown
[English](README.md) · **Русский**
```

**Step 2: Commit**

```bash
git add README_RU.md
git commit -m "docs: add Russian README_RU.md"
```

---

### Task 5: Update cross-references

**Files:**
- Modify: `CLAUDE.md` (if it references old ARCHITECTURE.md path — verify)
- Modify: any other files referencing `docs/ARCHITECTURE.md` by name

**Step 1: Search for references to old paths**

```bash
grep -r "ARCHITECTURE" --include="*.md" .
```

Verify all references still point to valid files. Update if needed.

**Step 2: Commit (if changes needed)**

```bash
git commit -m "docs: fix cross-references after readme redesign"
```
