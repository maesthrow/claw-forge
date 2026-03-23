# ClawForge v3 — Stability & Correctness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix routing bugs, JSON parsing, extend_existing flow, security issues, and setup stability across 7 files.

**Architecture:** All changes are within existing modules — no new files. Each task modifies 1-2 files max. Changes are independent enough to commit separately.

**Tech Stack:** Python 3.10+, SQLite, OpenClaw CLI, shell (Linux server)

**Design doc:** `docs/plans/2026-03-24-v3-stability-design.md`

---

### Task 1: Fix registry.py — SQL injection + context managers

**Files:**
- Modify: `src/registry.py`

**Step 1: Add column whitelist and context managers**

Replace entire `src/registry.py` with:

```python
"""ClawForge agent registry — SQLite storage for agent metadata."""

import sqlite3
import json
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "clawforge.db")

ALLOWED_COLUMNS = {"description", "capabilities", "workspace_path", "parent_agent"}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                parent_agent TEXT,
                workspace_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def add_agent(name, agent_type, description, capabilities, workspace_path, parent_agent=None):
    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agents (name, type, description, capabilities, parent_agent, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, agent_type, description, json.dumps(capabilities, ensure_ascii=False), parent_agent, workspace_path, now, now)
        )


def remove_agent(name):
    with get_connection() as conn:
        conn.execute("DELETE FROM agents WHERE name = ?", (name,))


def update_agent(name, **kwargs):
    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        for key, value in kwargs.items():
            if key not in ALLOWED_COLUMNS:
                raise ValueError(f"Invalid column: {key}")
            if key == "capabilities":
                value = json.dumps(value, ensure_ascii=False)
            conn.execute(f"UPDATE agents SET {key} = ?, updated_at = ? WHERE name = ?", (value, now, name))


def get_agent(name):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        if row:
            return dict(row)
        return None


def list_agents():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


def search_agents(query):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agents WHERE description LIKE ? OR capabilities LIKE ?",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
        return [dict(r) for r in rows]
```

**Step 2: Verify**

Run: `cd /d/dev/ClawForge && python -c "import src.registry as r; r.init_db(); print(r.list_agents())"`
Expected: No errors, empty list or existing agents.

**Step 3: Commit**

```bash
git add src/registry.py
git commit -m "fix: SQL injection whitelist + context managers in registry.py"
```

---

### Task 2: Fix deploy.py — shlex.quote + switch_agent + delete_agent

**Files:**
- Modify: `src/deploy.py`

**Step 1: Add shlex import and rewrite functions**

Replace entire `src/deploy.py` with:

```python
"""ClawForge deploy module — OpenClaw agent management via CLI."""

import os
import shlex
import shutil
import subprocess


OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_MAIN_WORKSPACE = os.environ.get("CLAWFORGE_MAIN_WORKSPACE", "/root/.openclaw/workspace")


def run_cmd(cmd):
    """Run a shell command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nstderr: {result.stderr}")
    return result.stdout.strip()


def create_agent_workspace(name, soul_md, agents_md=None, skills=None):
    """Create workspace directory with SOUL.md and optional skills."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    os.makedirs(workspace, exist_ok=True)

    with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(soul_md)

    if agents_md:
        with open(os.path.join(workspace, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write(agents_md)

    if skills:
        skills_dir = os.path.join(workspace, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        for skill_name, skill_content in skills.items():
            skill_dir = os.path.join(skills_dir, skill_name)
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_content)

    # Clean OpenClaw default templates from workspace
    clean_openclaw_defaults(workspace)

    return workspace


def register_agent(name, workspace_path):
    """Register agent in OpenClaw gateway."""
    result = run_cmd(f"openclaw agents add {shlex.quote(name)} --workspace {shlex.quote(workspace_path)} --non-interactive")

    # OpenClaw creates a default workspace-<name>/ dir with template files.
    # Remove all defaults and copy our files instead.
    openclaw_home = os.path.expanduser("~/.openclaw")
    default_workspace = os.path.join(openclaw_home, f"workspace-{name}")
    if os.path.exists(default_workspace):
        for fname in os.listdir(default_workspace):
            fpath = os.path.join(default_workspace, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)

        for fname in os.listdir(workspace_path):
            src = os.path.join(workspace_path, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(default_workspace, fname))

        our_skills = os.path.join(workspace_path, "skills")
        default_skills = os.path.join(default_workspace, "skills")
        if os.path.exists(our_skills):
            if os.path.exists(default_skills):
                shutil.rmtree(default_skills)
            shutil.copytree(our_skills, default_skills)

    # Clean defaults from main workspace too
    clean_openclaw_defaults(workspace_path)

    return result


def delete_agent(name):
    """Delete agent from OpenClaw and remove all artifacts."""
    try:
        run_cmd(f"openclaw agents delete {shlex.quote(name)} --force")
    except RuntimeError:
        pass

    # Remove our workspace
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        shutil.rmtree(workspace)

    # Remove OpenClaw agent state (sessions, cache)
    openclaw_home = os.path.expanduser("~/.openclaw")
    agent_state = os.path.join(openclaw_home, "agents", name)
    if os.path.exists(agent_state):
        shutil.rmtree(agent_state)


def update_agent_soul(name, soul_md):
    """Update SOUL.md for an existing agent."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
            f.write(soul_md)

    # Also update workspace-<name> if it exists
    openclaw_home = os.path.expanduser("~/.openclaw")
    default_workspace = os.path.join(openclaw_home, f"workspace-{name}")
    if os.path.exists(default_workspace):
        with open(os.path.join(default_workspace, "SOUL.md"), "w", encoding="utf-8") as f:
            f.write(soul_md)


def add_skill_to_agent(agent_name, skill_name, skill_content):
    """Add a skill to an existing agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    skill_dir = os.path.join(workspace, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


def add_heartbeat(name, cron_expr, agent_name, message, telegram_user_id):
    """Create a cron job in OpenClaw."""
    return run_cmd(
        f"openclaw cron add --name {shlex.quote(name)} --cron {shlex.quote(cron_expr)} "
        f"--agent {shlex.quote(agent_name)} --message {shlex.quote(message)} "
        f"--deliver telegram:{shlex.quote(telegram_user_id)}"
    )


def switch_agent(agent_name, telegram_user_id):
    """Switch Telegram routing to a different agent via agents bind."""
    openclaw_name = "main" if agent_name == "architect" else agent_name

    # Clear existing routing
    run_cmd("openclaw config set bindings '[]'")

    # Bind target agent — sets correct accountId in sessions for /new
    run_cmd(
        f"openclaw agents bind --agent {shlex.quote(openclaw_name)} "
        f"--bind telegram:{shlex.quote(telegram_user_id)}"
    )


def call_agent(agent_name, message):
    """Send a message to an agent and get the response."""
    return run_cmd(
        f"openclaw agent --agent {shlex.quote(agent_name)} "
        f"--message {shlex.quote(message)} --timeout 600"
    )


def send_notification(channel, user_id, message):
    """Send a notification message to user via OpenClaw."""
    try:
        run_cmd(
            f"openclaw message send --channel {shlex.quote(channel)} "
            f"--target {shlex.quote(user_id)} -m {shlex.quote(message)}"
        )
    except RuntimeError as e:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "notification_errors.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"Failed to send to {channel}:{user_id} — {str(e)[:200]}\n")


def install_skill_to_architect(skill_name, skill_content):
    """Install a skill into the architect's workspace."""
    skill_dir = os.path.join(OPENCLAW_MAIN_WORKSPACE, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


OPENCLAW_DEFAULTS = ["BOOTSTRAP.md", "IDENTITY.md", "USER.md", "TOOLS.md", "HEARTBEAT.md"]


def clean_openclaw_defaults(workspace_path, keep_agents_md=False):
    """Remove OpenClaw default template files from workspace."""
    to_remove = list(OPENCLAW_DEFAULTS)
    if not keep_agents_md:
        to_remove.append("AGENTS.md")
    for fname in to_remove:
        fpath = os.path.join(workspace_path, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
```

**Step 2: Verify syntax**

Run: `cd /d/dev/ClawForge && python -c "import src.deploy as d; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add src/deploy.py
git commit -m "fix: shlex.quote shell injection, agents bind routing, full delete cleanup"
```

---

### Task 3: Fix orchestration.py — JSON parser + stale prompts + validation + extend_existing

**Files:**
- Modify: `src/orchestration.py`

**Step 1: Add imports and validation function at top**

After existing imports, add:

```python
import re

import deploy
import registry


def validate_agent_name(name):
    """Validate agent name: lowercase letters, digits, underscores only."""
    if not re.match(r'^[a-z][a-z0-9_]{1,49}$', name):
        raise ValueError(f"Invalid agent name: '{name}'. Use lowercase letters, digits, underscores. Start with letter. Max 50 chars.")
```

**Step 2: Fix parse_json_response — direct parse first**

Replace `parse_json_response` function (lines 327-349):

```python
def parse_json_response(response):
    """Extract JSON from LLM response, handling markdown code blocks and extra text."""
    text = response.strip()

    # 1. Try direct parse first (handles clean JSON with backticks inside values)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try stripping markdown code blocks
    stripped = text
    if "```json" in stripped:
        stripped = stripped.split("```json")[1].split("```")[0]
    elif "```" in stripped:
        stripped = stripped.split("```")[1].split("```")[0]

    # 3. Try to find JSON object/array boundaries
    stripped = stripped.strip()
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = stripped.find(start_char)
        if start != -1:
            end = stripped.rfind(end_char)
            if end != -1:
                try:
                    return json.loads(stripped[start:end + 1])
                except json.JSONDecodeError:
                    continue

    return json.loads(stripped)
```

**Step 3: Add prompt builder functions**

Add before `run_pipeline`:

```python
def build_tester_prompt(requirements, artifacts):
    """Build tester prompt with current artifacts."""
    return f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Есть ли блок "Правило первого сообщения" с командами /main и /new?
5. Есть ли блок "Команда возврата" с python3 /opt/clawforge/src/main.py switch --agent architect?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению"]
}}

Верни ТОЛЬКО JSON."""


def build_validator_prompt(requirements, artifacts, test_report):
    """Build validator prompt with current artifacts."""
    return f"""Финальная проверка агента перед деплоем.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Отчёт тестировщика:
{json.dumps(test_report, ensure_ascii=False, indent=2)}

Верни JSON:
{{
  "approved": true/false,
  "reason": "причина"
}}

Верни ТОЛЬКО JSON."""
```

**Step 4: Fix run_pipeline — add validation + use prompt builders**

In `run_pipeline`, after `requirements = call_agent_with_retry("analyst", analyst_prompt)` (line 41), add:

```python
    # Validate agent name
    if requirements.get("agent_name"):
        validate_agent_name(requirements["agent_name"])
```

Replace the tester+validator cycle (lines 121-222) with:

```python
    # 6. Tester + Validator cycle with retry
    max_tester_retries = 2
    max_validator_retries = 1

    for validator_attempt in range(max_validator_retries + 1):
        # Tester
        test_report = call_agent_with_retry("tester", build_tester_prompt(requirements, artifacts))

        # Tester reject → developer fix (max retries)
        tester_retries = 0
        while not test_report.get("approved", False) and tester_retries < max_tester_retries:
            fix_prompt = f"""Тестировщик нашёл проблемы в артефактах.

Проблемы: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Предложения: {json.dumps(test_report.get('fixes', []), ensure_ascii=False)}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь и верни обновлённый JSON в том же формате.
ВАЖНО: команды /main и /new должны быть сохранены с символом косой черты."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            test_report = call_agent_with_retry("tester", build_tester_prompt(requirements, artifacts))
            tester_retries += 1

        if not test_report.get("approved", False):
            return {
                "action": "rejected",
                "reason": f"Тестировщик не одобрил после {max_tester_retries} попыток исправления.",
                "message": "Не удалось создать агента: тестировщик нашёл неисправимые проблемы."
            }

        # Validator
        validation = call_agent_with_retry("validator", build_validator_prompt(requirements, artifacts, test_report))

        if validation.get("approved", False):
            break

        # Validator rejected → retry with fix
        if validator_attempt < max_validator_retries:
            fix_prompt = f"""Валидатор отклонил агента.

Причина: {validation.get('reason', 'не указана')}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь причину отказа и верни обновлённый JSON в том же формате.
ВАЖНО: команды /main и /new должны быть сохранены с символом косой черты."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            continue

        return {
            "action": "rejected",
            "reason": validation.get("reason", "Валидатор отклонил"),
            "message": f"Не удалось создать агента: {validation.get('reason')}. Попробуйте уточнить задачу."
        }
```

**Step 5: Fix deploy_extension — update SOUL.md**

Replace `deploy_extension` function (lines 233-261):

```python
def deploy_extension(requirements, artifacts):
    """Deploy skill/heartbeat extension to an existing agent. Updates SOUL.md if provided."""
    target_agent = requirements["extend_agent"]
    agent_name = requirements["agent_name"]

    # Update SOUL.md if provided
    if artifacts.get("soul_md"):
        deploy.update_agent_soul(target_agent, artifacts["soul_md"])

    # Add skills
    for skill_name, skill_content in artifacts.get("skills", {}).items():
        deploy.add_skill_to_agent(target_agent, skill_name, skill_content)

    # Add heartbeat if needed
    if requirements.get("needs_heartbeat"):
        telegram_user_id = get_telegram_user_id()
        deploy.add_heartbeat(
            name=f"{target_agent}-{agent_name}",
            cron_expr=requirements["heartbeat_schedule"],
            agent_name=target_agent,
            message=requirements["heartbeat_message"],
            telegram_user_id=telegram_user_id
        )

    # Update capabilities in registry
    existing_agent = registry.get_agent(target_agent)
    if existing_agent:
        old_caps = json.loads(existing_agent["capabilities"])
        new_caps = list(set(old_caps + requirements["capabilities"]))
        registry.update_agent(target_agent, capabilities=new_caps,
                              description=requirements["description"])

    action_msg = "обновлён" if artifacts.get("soul_md") else "расширен: добавлены новые навыки"
    return {
        "action": "extended",
        "agent_name": target_agent,
        "message": f"Агент '{target_agent}' {action_msg}."
    }
```

**Step 6: Fix get_telegram_user_id — read from config file**

Replace `get_telegram_user_id` function (lines 398-400):

```python
def get_telegram_user_id():
    """Get Telegram user ID from config file or environment."""
    # 1. Config file (set by setup.py)
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".telegram_id")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid

    # 2. Environment variable
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
```

**Step 7: Verify syntax**

Run: `cd /d/dev/ClawForge && python -c "import src.orchestration as o; print('ok')"`
Expected: `ok`

**Step 8: Commit**

```bash
git add src/orchestration.py
git commit -m "fix: JSON parser, stale prompts, extend_existing SOUL.md, agent name validation"
```

---

### Task 4: Fix main.py — telegram ID from config

**Files:**
- Modify: `src/main.py`

**Step 1: Replace hardcoded telegram ID in cmd_switch**

Replace line 74:

```python
    telegram_user_id = os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
```

With:

```python
    telegram_user_id = _get_telegram_user_id()
```

Add helper function before `cmd_switch`:

```python
def _get_telegram_user_id():
    """Get Telegram user ID from config file or environment."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".telegram_id")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
```

**Step 2: Commit**

```bash
git add src/main.py
git commit -m "fix: read telegram ID from config file instead of hardcode"
```

---

### Task 5: Update architect SOUL.md — stable greeting

**Files:**
- Modify: `agents/architect/SOUL.md`

**Step 1: Replace greeting section**

Replace lines 15-25 (the "Первое сообщение в сессии" section) with:

```markdown
## Первое сообщение в сессии

При первом сообщении в новой сессии отправь РОВНО ОДНО сообщение по этому шаблону:

Привет! Я ClawForge, архитектор AI-агентов.

Я помогаю проектировать, создавать и управлять командой специализированных AI-агентов под ваши задачи.

/list — показать список агентов
/set <имя> — переключиться на агента
/rm <имя> — удалить агента
/new — новая сессия

Что хочешь сделать?

Допускается перефразировка, но структура обязательна: приветствие → описание → команды отдельным блоком → вопрос.
```

**Step 2: Commit**

```bash
git add agents/architect/SOUL.md
git commit -m "fix: stable greeting template in architect SOUL.md"
```

---

### Task 6: Parameterize SKILL.md — telegram ID placeholder

**Files:**
- Modify: `skills/claw-forge/SKILL.md`

**Step 1: Replace hardcoded telegram ID with placeholder**

Replace line 47:

```
python3 /opt/clawforge/src/main.py create --task "<описание задачи пользователя>" --notify telegram:541534272
```

With:

```
python3 /opt/clawforge/src/main.py create --task "<описание задачи пользователя>" --notify telegram:{{TELEGRAM_USER_ID}}
```

**Step 2: Commit**

```bash
git add skills/claw-forge/SKILL.md
git commit -m "fix: parameterize telegram ID in SKILL.md template"
```

---

### Task 7: Fix setup.py — cleanup defaults + telegram ID auto-detect + SKILL.md templating

**Files:**
- Modify: `setup.py`

**Step 1: Full rewrite of setup.py**

Replace entire `setup.py` with:

```python
#!/usr/bin/env python3
"""ClawForge setup script — installs/updates/uninstalls on an OpenClaw server."""

import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
MAIN_WORKSPACE = os.path.join(OPENCLAW_HOME, "workspace")
WORKSPACES_DIR = os.path.join(OPENCLAW_HOME, "workspaces")
TELEGRAM_ID_FILE = os.path.join(SCRIPT_DIR, ".telegram_id")

BASE_AGENTS = ["analyst", "developer", "tester", "validator"]

OPENCLAW_DEFAULTS = ["BOOTSTRAP.md", "IDENTITY.md", "USER.md", "TOOLS.md", "HEARTBEAT.md"]


def run_cmd(cmd):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        print(f"  WARN: {result.stderr.strip()}")
    return result.returncode == 0


def protect_file(path):
    """Make file read-only (chmod 444)."""
    if os.path.exists(path):
        os.chmod(path, 0o444)


def unprotect_file(path):
    """Restore file to writable (chmod 644)."""
    if os.path.exists(path):
        os.chmod(path, 0o644)


def clean_workspace_defaults(workspace_path, keep_agents_md=False):
    """Remove OpenClaw default template files from workspace."""
    to_remove = list(OPENCLAW_DEFAULTS)
    if not keep_agents_md:
        to_remove.append("AGENTS.md")
    for fname in to_remove:
        fpath = os.path.join(workspace_path, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print(f"    removed {fname}")


def detect_telegram_id():
    """Auto-detect Telegram user ID from OpenClaw pairing data."""
    allow_path = os.path.join(OPENCLAW_HOME, "credentials", "telegram-default-allowFrom.json")
    if os.path.exists(allow_path):
        try:
            with open(allow_path) as f:
                data = json.load(f)
            ids = data.get("allowFrom", [])
            if ids:
                return ids[0]
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def get_telegram_id():
    """Get Telegram ID: saved file → auto-detect → None."""
    if os.path.exists(TELEGRAM_ID_FILE):
        with open(TELEGRAM_ID_FILE, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid

    tid = detect_telegram_id()
    if tid:
        save_telegram_id(tid)
    return tid


def save_telegram_id(tid):
    """Save Telegram ID to config file."""
    with open(TELEGRAM_ID_FILE, "w") as f:
        f.write(tid)
    print(f"  Telegram ID saved: {tid}")


def install_skill(src_path, dst_path, telegram_id):
    """Install SKILL.md with Telegram ID substitution."""
    with open(src_path, "r", encoding="utf-8") as f:
        content = f.read()
    if telegram_id:
        content = content.replace("{{TELEGRAM_USER_ID}}", telegram_id)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(content)


def install():
    print("=== ClawForge Setup ===\n")

    # Detect Telegram ID
    telegram_id = get_telegram_id()
    if not telegram_id:
        print("  WARNING: Telegram not paired yet. Run 'openclaw pairing approve telegram <CODE>' first.")
        print("  After pairing, run: python setup.py --update\n")

    total_steps = len(BASE_AGENTS) + 4

    # 1. Base agents
    for i, agent in enumerate(BASE_AGENTS, 1):
        print(f"[{i}/{total_steps}] Creating agent {agent}...")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        os.makedirs(workspace, exist_ok=True)

        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        shutil.copy2(src_soul, dst_soul)

        run_cmd(f'openclaw agents add {agent} --workspace "{workspace}" --non-interactive')

        # Clean OpenClaw defaults from workspace
        clean_workspace_defaults(workspace, keep_agents_md=False)

        # Clean workspace-<name> if exists
        default_ws = os.path.join(OPENCLAW_HOME, f"workspace-{agent}")
        if os.path.exists(default_ws):
            for fname in os.listdir(default_ws):
                fpath = os.path.join(default_ws, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            shutil.copy2(src_soul, os.path.join(default_ws, "SOUL.md"))
        print(f"  done")

    # 2. Architect SOUL.md + AGENTS.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{total_steps}] Configuring architect...")

    clean_workspace_defaults(MAIN_WORKSPACE, keep_agents_md=True)

    src_soul = os.path.join(SCRIPT_DIR, "agents", "architect", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)

    src_agents = os.path.join(SCRIPT_DIR, "agents", "architect", "AGENTS.md")
    dst_agents = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
    print("  done")

    # 3. claw-forge skill
    step += 1
    print(f"[{step}/{total_steps}] Installing skill claw-forge...")
    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    install_skill(src_skill, dst_skill, telegram_id)
    print("  done")

    # 4. Init registry
    step += 1
    print(f"[{step}/{total_steps}] Initializing registry...")
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
    import registry
    registry.init_db()
    print("  done")

    # 5. Protect architect config files (read-only)
    step += 1
    print(f"[{step}/{total_steps}] Protecting architect config files...")
    protect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))
    print("  done")

    print(f"\n=== ClawForge installed! ===")
    print(f"Base agents: {len(BASE_AGENTS) + 1} (architect + {', '.join(BASE_AGENTS)})")
    if telegram_id:
        print(f"Telegram ID: {telegram_id}")
    print(f"Send your bot a message in Telegram to start.")


def update():
    print("=== ClawForge Update ===\n")

    # Detect/update Telegram ID
    telegram_id = get_telegram_id()
    if not telegram_id:
        # Try fresh detection
        telegram_id = detect_telegram_id()
        if telegram_id:
            save_telegram_id(telegram_id)
        else:
            print("  WARNING: Telegram ID not found. SKILL.md will have unresolved placeholder.")

    # Unprotect before updating
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    # Update base agents
    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        if os.path.exists(workspace):
            shutil.copy2(src_soul, dst_soul)
            clean_workspace_defaults(workspace, keep_agents_md=False)
            print(f"  {agent} updated")

    # Update architect
    src_soul = os.path.join(SCRIPT_DIR, "agents", "architect", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  architect SOUL.md updated")

    src_agents = os.path.join(SCRIPT_DIR, "agents", "architect", "AGENTS.md")
    dst_agents = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
    print("  architect AGENTS.md updated")

    # Clean defaults from main workspace
    clean_workspace_defaults(MAIN_WORKSPACE, keep_agents_md=True)

    # Update skill with Telegram ID
    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    install_skill(src_skill, dst_skill, telegram_id)
    print("  skill claw-forge updated")

    # Re-protect after updating
    protect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    print("\n=== Update complete ===")
    if telegram_id:
        print(f"Telegram ID: {telegram_id}")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    # Unprotect architect files before removal
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    for agent in BASE_AGENTS:
        print(f"  Removing agent {agent}...")
        run_cmd(f"openclaw agents delete {agent} --force")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        print(f"  done")

    agents_md = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(agents_md):
        os.remove(agents_md)
        print("  architect AGENTS.md removed")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)
        print("  skill claw-forge removed")

    db_path = os.path.join(SCRIPT_DIR, "clawforge.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  registry removed")

    if os.path.exists(TELEGRAM_ID_FILE):
        os.remove(TELEGRAM_ID_FILE)
        print("  telegram ID config removed")

    print("\n=== ClawForge uninstalled. OpenClaw is clean. ===")


def main():
    parser = argparse.ArgumentParser(description="ClawForge setup")
    parser.add_argument("--update", action="store_true", help="Update SOUL.md and skills")
    parser.add_argument("--uninstall", action="store_true", help="Remove ClawForge from OpenClaw")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    elif args.update:
        update()
    else:
        install()


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

Run: `cd /d/dev/ClawForge && python -c "import setup; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add setup.py
git commit -m "fix: cleanup OpenClaw defaults, auto-detect telegram ID, SKILL.md templating"
```

---

### Task 8: Deploy and verify on server

**Step 1: Push changes and pull on server**

```bash
git push origin master
ssh root@194.113.37.137 "cd /opt/clawforge && git pull"
```

**Step 2: Run update**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && python3 setup.py --update"
```

Expected: All agents updated, defaults cleaned, Telegram ID detected and applied.

**Step 3: Verify cleanup**

```bash
ssh root@194.113.37.137 "ls /root/.openclaw/workspaces/analyst/"
```

Expected: Only `SOUL.md` (no BOOTSTRAP.md, IDENTITY.md, etc.)

```bash
ssh root@194.113.37.137 "ls /root/.openclaw/workspace/"
```

Expected: `AGENTS.md`, `SOUL.md`, `skills/` (no IDENTITY.md, TOOLS.md, HEARTBEAT.md)

**Step 4: Verify SKILL.md has real telegram ID**

```bash
ssh root@194.113.37.137 "grep 'notify' /root/.openclaw/workspace/skills/claw-forge/SKILL.md"
```

Expected: `--notify telegram:541534272` (real ID, not placeholder)

**Step 5: Test /new routing in Telegram**

1. Send `/set linkedin_writer` — should switch
2. Send `/main` — should switch to architect
3. Send `/new` — should start new session with architect (not linkedin_writer)

**Step 6: Test agent creation in Telegram**

1. Ask architect to create a simple test agent
2. Verify pipeline completes without JSON parse errors
3. Verify `/list` shows the new agent

**Step 7: Test agent deletion**

1. `/rm <test_agent>` — confirm and delete
2. Verify `ls /root/.openclaw/agents/<test_agent>` — should not exist
3. Verify `/list` — should not show deleted agent
