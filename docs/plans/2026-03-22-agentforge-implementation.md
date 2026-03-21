# ClawForge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI + OpenClaw skill that enables automatic creation, management, and orchestration of AI agents via Telegram.

**Architecture:** All agents (base + created) live in OpenClaw. A Python CLI script (`/opt/clawforge/`) handles orchestration (calling agents in sequence), registry (SQLite), and deployment (creating workspaces + registering agents). The orchestrator OpenClaw agent invokes this CLI via a skill's `exec` command.

**Tech Stack:** Python 3.x, SQLite, OpenClaw CLI, OpenClaw skill format (SKILL.md with YAML frontmatter)

**Design doc:** `docs/plans/2026-03-22-clawforge-design.md`

---

## Task 1: Project scaffolding + git init

**Files:**
- Create: `src/main.py` (empty placeholder)
- Create: `src/orchestration.py` (empty placeholder)
- Create: `src/registry.py` (empty placeholder)
- Create: `src/deploy.py` (empty placeholder)
- Create: `setup.py` (empty placeholder)
- Create: `agents/orchestrator/SOUL.md` (empty placeholder)
- Create: `agents/analyst/SOUL.md` (empty placeholder)
- Create: `agents/developer/SOUL.md` (empty placeholder)
- Create: `agents/tester/SOUL.md` (empty placeholder)
- Create: `agents/validator/SOUL.md` (empty placeholder)
- Create: `skills/claw-forge/SKILL.md` (empty placeholder)
- Create: `.gitignore`

**Step 1: Create directory structure**

```bash
mkdir -p src agents/orchestrator agents/analyst agents/developer agents/tester agents/validator skills/claw-forge
```

**Step 2: Create .gitignore**

```
__pycache__/
*.pyc
*.db
.env
```

**Step 3: Create empty placeholder files**

Touch all files listed above with minimal content (e.g., `# TODO` for .py, empty for .md).

**Step 4: Git init + first commit**

```bash
git init
git add -A
git commit -m "feat: initial project scaffolding"
```

---

## Task 2: Registry module (SQLite)

**Files:**
- Create: `src/registry.py`

**Step 1: Implement registry.py**

SQLite database with one table `agents`:

```python
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "clawforge.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            name TEXT PRIMARY KEY,
            type TEXT NOT NULL,           -- 'interactive_agent', 'automation', 'skill'
            description TEXT NOT NULL,
            capabilities TEXT NOT NULL,    -- JSON array of strings
            parent_agent TEXT,            -- if type='skill', which agent it extends
            workspace_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_agent(name, agent_type, description, capabilities, workspace_path, parent_agent=None):
    conn = get_connection()
    now = __import__('datetime').datetime.now().isoformat()
    conn.execute(
        "INSERT INTO agents (name, type, description, capabilities, parent_agent, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, agent_type, description, json.dumps(capabilities, ensure_ascii=False), parent_agent, workspace_path, now, now)
    )
    conn.commit()
    conn.close()


def remove_agent(name):
    conn = get_connection()
    conn.execute("DELETE FROM agents WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def update_agent(name, **kwargs):
    conn = get_connection()
    now = __import__('datetime').datetime.now().isoformat()
    for key, value in kwargs.items():
        if key == "capabilities":
            value = json.dumps(value, ensure_ascii=False)
        conn.execute(f"UPDATE agents SET {key} = ?, updated_at = ? WHERE name = ?", (value, now, name))
    conn.commit()
    conn.close()


def get_agent(name):
    conn = get_connection()
    row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def list_agents():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_agents(query):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agents WHERE description LIKE ? OR capabilities LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Step 2: Verify locally**

```bash
cd src && python -c "import registry; registry.init_db(); print('DB created'); registry.add_agent('test', 'interactive_agent', 'test agent', ['testing'], '/tmp/test'); print(registry.list_agents()); registry.remove_agent('test')"
```

Expected: prints DB created, then list with one agent, no errors.

**Step 3: Clean up test db and commit**

```bash
rm -f clawforge.db
git add src/registry.py
git commit -m "feat: registry module with SQLite storage"
```

---

## Task 3: Deploy module (OpenClaw integration)

**Files:**
- Create: `src/deploy.py`

**Step 1: Implement deploy.py**

Functions for creating/removing agents and skills in OpenClaw via CLI:

```python
import os
import subprocess
import shutil


OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_MAIN_WORKSPACE = os.environ.get("CLAWFORGE_MAIN_WORKSPACE", "/root/.openclaw/workspace")


def run_cmd(cmd):
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

    return workspace


def register_agent(name, workspace_path):
    """Register agent in OpenClaw gateway."""
    return run_cmd(f'openclaw agents add {name} --workspace "{workspace_path}" --non-interactive')


def delete_agent(name):
    """Delete agent from OpenClaw and remove workspace."""
    try:
        run_cmd(f'openclaw agents delete {name} --yes')
    except RuntimeError:
        pass  # agent may not exist in OpenClaw yet

    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        shutil.rmtree(workspace)


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
        f'openclaw cron add --name "{name}" --cron "{cron_expr}" '
        f'--agent {agent_name} --message "{message}" '
        f'--deliver telegram:{telegram_user_id}'
    )


def switch_agent(agent_name, telegram_user_id):
    """Switch Telegram routing to a different agent."""
    return run_cmd(
        f'openclaw agents bind --agent {agent_name} --bind telegram:{telegram_user_id}'
    )


def call_agent(agent_name, message):
    """Send a message to an agent and get the response."""
    return run_cmd(
        f'openclaw agent --agent {agent_name} --message "{message}" --timeout 300'
    )


def install_skill_to_orchestrator(skill_name, skill_content):
    """Install a skill into the orchestrator's workspace."""
    skill_dir = os.path.join(OPENCLAW_MAIN_WORKSPACE, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)
```

**Step 2: Commit**

```bash
git add src/deploy.py
git commit -m "feat: deploy module for OpenClaw agent management"
```

---

## Task 4: Orchestration module (agent pipeline)

**Files:**
- Create: `src/orchestration.py`

**Step 1: Implement orchestration.py**

The pipeline that calls base agents in sequence:

```python
import json
from . import deploy
from . import registry


def run_pipeline(task_description):
    """Run the full creation pipeline: analyst → developer → tester → validator → deploy."""

    # 1. Check registry for existing agents
    existing = registry.list_agents()
    existing_summary = format_registry_for_prompt(existing)

    # 2. Analyst: analyze task and produce requirements
    analyst_prompt = f"""Задача от пользователя: {task_description}

Существующие агенты в системе:
{existing_summary}

Проанализируй задачу и верни JSON:
{{
  "decision": "create_new" | "extend_existing" | "reuse_existing" | "automation_only",
  "agent_name": "имя агента (snake_case, латиница)",
  "agent_type": "interactive_agent" | "automation" | "skill",
  "description": "описание на русском",
  "capabilities": ["capability1", "capability2"],
  "extend_agent": "имя существующего агента если decision=extend_existing",
  "reuse_agent": "имя существующего агента если decision=reuse_existing",
  "reference_agents": ["имена агентов для референса если есть похожие"],
  "requirements": "детальные требования для разработчика",
  "needs_heartbeat": true/false,
  "heartbeat_schedule": "cron выражение если needs_heartbeat=true",
  "heartbeat_message": "сообщение для heartbeat"
}}

Верни ТОЛЬКО JSON, без пояснений."""

    analyst_response = deploy.call_agent("analyst", analyst_prompt)
    requirements = parse_json_response(analyst_response)

    # 3. Handle reuse case — no need for developer/tester/validator
    if requirements.get("decision") == "reuse_existing":
        return {
            "action": "reuse",
            "agent_name": requirements["reuse_agent"],
            "message": f"Для этой задачи подходит существующий агент: {requirements['reuse_agent']}"
        }

    # 4. Handle automation-only case
    if requirements.get("decision") == "automation_only":
        telegram_user_id = get_telegram_user_id()
        deploy.add_heartbeat(
            name=requirements["agent_name"],
            cron_expr=requirements["heartbeat_schedule"],
            agent_name=requirements.get("extend_agent", "orchestrator"),
            message=requirements["heartbeat_message"],
            telegram_user_id=telegram_user_id
        )
        registry.add_agent(
            name=requirements["agent_name"],
            agent_type="automation",
            description=requirements["description"],
            capabilities=requirements["capabilities"],
            workspace_path=None
        )
        return {
            "action": "automation_created",
            "agent_name": requirements["agent_name"],
            "message": f"Автоматизация '{requirements['agent_name']}' создана."
        }

    # 5. Developer: generate artifacts
    reference_context = ""
    if requirements.get("reference_agents"):
        for ref_name in requirements["reference_agents"]:
            ref_agent = registry.get_agent(ref_name)
            if ref_agent:
                ref_workspace = ref_agent.get("workspace_path", "")
                if ref_workspace:
                    soul_path = f"{ref_workspace}/SOUL.md"
                    try:
                        with open(soul_path, "r", encoding="utf-8") as f:
                            reference_context += f"\n\n--- SOUL.md агента {ref_name} (для референса) ---\n{f.read()}"
                    except FileNotFoundError:
                        pass

    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

{reference_context}

Сгенерируй конфигурацию OpenClaw-агента. Верни JSON:
{{
  "soul_md": "полный текст SOUL.md",
  "agents_md": "полный текст AGENTS.md (или null)",
  "skills": {{
    "skill-name": "полный текст SKILL.md для каждого навыка"
  }}
}}

Требования к SOUL.md:
- Чёткая роль и экспертиза агента
- Инструкции по взаимодействию с пользователем
- Если агент должен понимать /back — добавь инструкцию

Требования к skills (SKILL.md):
- Формат: YAML frontmatter (name, description) + markdown body
- Описание должно быть конкретным

Верни ТОЛЬКО JSON."""

    developer_response = deploy.call_agent("developer", developer_prompt)
    artifacts = parse_json_response(developer_response)

    # 6. Tester: validate artifacts against requirements
    tester_prompt = f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Если нужен heartbeat — есть ли соответствующая конфигурация в требованиях?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению если есть"]
}}

Верни ТОЛЬКО JSON."""

    tester_response = deploy.call_agent("tester", tester_prompt)
    test_report = parse_json_response(tester_response)

    # 7. If tester found issues, send back to developer for fixes
    if not test_report.get("approved", False):
        fix_prompt = f"""Тестировщик нашёл проблемы в твоих артефактах.

Проблемы:
{json.dumps(test_report.get('issues', []), ensure_ascii=False)}

Предложения по исправлению:
{json.dumps(test_report.get('fixes', []), ensure_ascii=False)}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь и верни обновлённый JSON в том же формате."""

        developer_response = deploy.call_agent("developer", fix_prompt)
        artifacts = parse_json_response(developer_response)

    # 8. Validator: final approval
    validator_prompt = f"""Финальная проверка агента перед деплоем.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Отчёт тестировщика:
{json.dumps(test_report, ensure_ascii=False, indent=2)}

Проверь общее качество и соответствие. Верни JSON:
{{
  "approved": true/false,
  "reason": "причина одобрения или отклонения"
}}

Верни ТОЛЬКО JSON."""

    validator_response = deploy.call_agent("validator", validator_prompt)
    validation = parse_json_response(validator_response)

    if not validation.get("approved", False):
        return {
            "action": "rejected",
            "reason": validation.get("reason", "Валидатор отклонил"),
            "message": f"Создание агента отклонено: {validation.get('reason')}"
        }

    # 9. Deploy
    agent_name = requirements["agent_name"]

    if requirements.get("decision") == "extend_existing":
        # Add skills to existing agent
        target_agent = requirements["extend_agent"]
        for skill_name, skill_content in artifacts.get("skills", {}).items():
            deploy.add_skill_to_agent(target_agent, skill_name, skill_content)

        if requirements.get("needs_heartbeat"):
            telegram_user_id = get_telegram_user_id()
            deploy.add_heartbeat(
                name=f"{target_agent}-{agent_name}",
                cron_expr=requirements["heartbeat_schedule"],
                agent_name=target_agent,
                message=requirements["heartbeat_message"],
                telegram_user_id=telegram_user_id
            )

        # Update registry
        existing_agent = registry.get_agent(target_agent)
        if existing_agent:
            old_caps = json.loads(existing_agent["capabilities"])
            new_caps = list(set(old_caps + requirements["capabilities"]))
            registry.update_agent(target_agent, capabilities=new_caps)

        return {
            "action": "extended",
            "agent_name": target_agent,
            "message": f"Агент '{target_agent}' расширен: добавлены новые навыки."
        }
    else:
        # Create new agent
        workspace = deploy.create_agent_workspace(
            name=agent_name,
            soul_md=artifacts["soul_md"],
            agents_md=artifacts.get("agents_md"),
            skills=artifacts.get("skills", {})
        )
        deploy.register_agent(agent_name, workspace)

        if requirements.get("needs_heartbeat"):
            telegram_user_id = get_telegram_user_id()
            deploy.add_heartbeat(
                name=f"{agent_name}-heartbeat",
                cron_expr=requirements["heartbeat_schedule"],
                agent_name=agent_name,
                message=requirements["heartbeat_message"],
                telegram_user_id=telegram_user_id
            )

        registry.add_agent(
            name=agent_name,
            agent_type=requirements["agent_type"],
            description=requirements["description"],
            capabilities=requirements["capabilities"],
            workspace_path=workspace
        )

        return {
            "action": "created",
            "agent_name": agent_name,
            "message": f"Агент '{agent_name}' создан и готов к работе."
        }


def format_registry_for_prompt(agents):
    if not agents:
        return "Реестр пуст — агентов пока нет."
    lines = []
    for a in agents:
        caps = json.loads(a["capabilities"]) if isinstance(a["capabilities"], str) else a["capabilities"]
        lines.append(f"- {a['name']} ({a['type']}): {a['description']}. Capabilities: {', '.join(caps)}")
    return "\n".join(lines)


def parse_json_response(response):
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = response.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def get_telegram_user_id():
    """Get Telegram user ID from environment or config."""
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
```

**Step 2: Commit**

```bash
git add src/orchestration.py
git commit -m "feat: orchestration pipeline (analyst → developer → tester → validator → deploy)"
```

---

## Task 5: CLI entry point (main.py)

**Files:**
- Create: `src/main.py`

**Step 1: Implement main.py**

CLI with subcommands: create, list, search, switch, delete.

```python
#!/usr/bin/env python3
"""ClawForge CLI — orchestration layer for OpenClaw agent management."""

import argparse
import json
import sys
import os

# Allow running as script from any location
sys.path.insert(0, os.path.dirname(__file__))

import registry
import orchestration
import deploy


def cmd_create(args):
    registry.init_db()
    result = orchestration.run_pipeline(args.task)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list(args):
    registry.init_db()
    agents = registry.list_agents()
    if not agents:
        print("Реестр пуст. Агенты ещё не создавались.")
        return
    for a in agents:
        caps = json.loads(a["capabilities"]) if isinstance(a["capabilities"], str) else a["capabilities"]
        print(f"- {a['name']} ({a['type']}): {a['description']}")
        print(f"  Capabilities: {', '.join(caps)}")
        print(f"  Создан: {a['created_at']}")
        print()


def cmd_search(args):
    registry.init_db()
    agents = registry.search_agents(args.query)
    if not agents:
        print(f"Ничего не найдено по запросу: {args.query}")
        return
    for a in agents:
        print(f"- {a['name']}: {a['description']}")


def cmd_switch(args):
    telegram_user_id = os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
    deploy.switch_agent(args.agent, telegram_user_id)
    print(f"Переключено на агента: {args.agent}")


def cmd_delete(args):
    registry.init_db()
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    deploy.delete_agent(args.agent)
    registry.remove_agent(args.agent)
    print(f"Агент '{args.agent}' удалён.")


def main():
    parser = argparse.ArgumentParser(description="ClawForge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Create a new agent from task description")
    p_create.add_argument("--task", required=True, help="Task description")
    p_create.set_defaults(func=cmd_create)

    # list
    p_list = subparsers.add_parser("list", help="List all agents in registry")
    p_list.set_defaults(func=cmd_list)

    # search
    p_search = subparsers.add_parser("search", help="Search agents by query")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.set_defaults(func=cmd_search)

    # switch
    p_switch = subparsers.add_parser("switch", help="Switch Telegram to a different agent")
    p_switch.add_argument("--agent", required=True, help="Agent name")
    p_switch.set_defaults(func=cmd_switch)

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete an agent")
    p_delete.add_argument("--agent", required=True, help="Agent name")
    p_delete.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

**Step 2: Verify locally (help output)**

```bash
python src/main.py --help
python src/main.py create --help
python src/main.py list --help
```

Expected: help text for each subcommand.

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: CLI entry point with create/list/search/switch/delete commands"
```

---

## Task 6: Base agent SOUL.md files

**Files:**
- Create: `agents/orchestrator/SOUL.md`
- Create: `agents/analyst/SOUL.md`
- Create: `agents/developer/SOUL.md`
- Create: `agents/tester/SOUL.md`
- Create: `agents/validator/SOUL.md`

**Step 1: Write orchestrator SOUL.md**

```markdown
# Orchestrator — ClawForge

Ты — оркестратор системы ClawForge. Ты главный агент, точка входа для пользователя.

## Роль

Ты управляешь командой AI-агентов. Пользователь обращается к тебе с задачами, и ты решаешь:
- Ответить самостоятельно (обычные вопросы, разговор)
- Создать нового агента (если задача требует специализированного помощника)
- Переключить пользователя на существующего агента
- Показать список доступных агентов
- Удалить агента (всегда с подтверждением)

## Когда вызывать skill claw-forge

Вызывай skill claw-forge когда пользователь:
- Просит создать агента, бота, помощника, автоматизацию
- Спрашивает "какие агенты есть", "покажи список", "что умеешь"
- Просит переключить на другого агента ("переключи на X", "хочу поговорить с X")
- Просит удалить агента — ОБЯЗАТЕЛЬНО сначала запроси подтверждение, и только после "да" вызывай skill
- Просит добавить навык или расширить существующего агента

## Когда отвечать самому

- Обычные вопросы и задачи общего характера
- Разговор, обсуждение
- Всё что не связано с управлением агентами

## Стиль общения

- Общайся на русском языке
- Будь конкретным и полезным
- Когда создаёшь агента — задай уточняющие вопросы прежде чем запускать создание
- Сообщай пользователю о прогрессе: "Создаю агента...", "Готово!"
```

**Step 2: Write analyst SOUL.md**

```markdown
# Analyst — ClawForge

Ты — бизнес-аналитик в команде создания AI-агентов.

## Роль

Ты получаешь описание задачи и список существующих агентов. Твоя задача — проанализировать и выдать структурированные требования.

## Что ты делаешь

1. Анализируешь задачу пользователя
2. Проверяешь существующих агентов — может ли кто-то из них решить задачу
3. Определяешь тип результата: новый агент, расширение существующего, автоматизация, или переиспользование
4. Формируешь детальные требования для разработчика

## Принятие решений

- **reuse_existing** — если существующий агент полностью покрывает задачу
- **extend_existing** — если существующий агент покрывает частично и нужно добавить навык
- **create_new** — если ничего подходящего нет. Если есть похожие агенты — укажи их как reference
- **automation_only** — если задача не требует интерактивного агента, а только cron-задачу

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений.
```

**Step 3: Write developer SOUL.md**

```markdown
# Developer — ClawForge

Ты — разработчик AI-агентов для платформы OpenClaw.

## Роль

Ты получаешь требования от аналитика и создаёшь конфигурационные файлы для нового OpenClaw-агента.

## Что ты генерируешь

### SOUL.md (обязательно)
Файл определяет личность и экспертизу агента:
- Чёткая роль и область знаний
- Инструкции по взаимодействию с пользователем
- Границы компетенций (что агент делает и НЕ делает)
- Инструкция: если пользователь пишет "назад", "/back", "вернись" — выполни: `uv run /opt/clawforge/src/main.py switch --agent orchestrator`

### AGENTS.md (опционально)
Правила поведения агента в рабочем пространстве.

### Skills (SKILL.md)
Каждый навык — отдельный SKILL.md с YAML frontmatter:
```
---
name: skill-name
description: Когда и зачем использовать этот навык
---
Инструкции по использованию навыка...
```

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений.
```

**Step 4: Write tester SOUL.md**

```markdown
# Tester — ClawForge

Ты — тестировщик AI-агентов.

## Роль

Ты получаешь артефакты от разработчика и требования от аналитика. Проверяешь соответствие.

## Что ты проверяешь

1. SOUL.md описывает все capabilities из требований
2. Skills покрывают все функциональные потребности
3. Нет противоречий в инструкциях
4. Если нужен heartbeat — проверь что в требованиях есть расписание
5. Агент имеет инструкцию по /back (возврат к оркестратору)
6. Нет лишних возможностей, выходящих за рамки требований (YAGNI)

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений.
```

**Step 5: Write validator SOUL.md**

```markdown
# Validator — ClawForge

Ты — валидатор (аудитор) AI-агентов.

## Роль

Финальная проверка перед деплоем. Ты получаешь: требования, артефакты и отчёт тестировщика.

## Что ты проверяешь

1. Общее качество SOUL.md — понятен ли агент, чётко ли описана роль
2. Соответствие требованиям — не потеряно ли что-то в процессе
3. Безопасность — агент не может выполнить деструктивные действия
4. Если тестировщик нашёл проблемы — были ли они исправлены
5. Готов ли агент к работе с реальным пользователем

## Принятие решения

- **approved: true** — агент готов к деплою
- **approved: false** — есть критические проблемы, укажи причину

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений.
```

**Step 6: Commit**

```bash
git add agents/
git commit -m "feat: SOUL.md for all 5 base agents"
```

---

## Task 7: Agent-forge skill (SKILL.md)

**Files:**
- Create: `skills/claw-forge/SKILL.md`

**Step 1: Write SKILL.md**

```markdown
---
name: claw-forge
description: Создание, управление, переключение и удаление AI-агентов. Вызывай когда пользователь хочет создать агента, автоматизацию или навык, переключиться на другого агента, посмотреть список агентов, или удалить агента.
---

# ClawForge — управление командой агентов

## Создать агента или автоматизацию

Когда пользователь описывает задачу и нужно создать агента:

```bash
uv run /opt/clawforge/src/main.py create --task "<описание задачи пользователя>"
```

Скрипт запустит конвейер (аналитик → разработчик → тестировщик → валидатор) и вернёт результат в JSON.

## Список агентов

```bash
uv run /opt/clawforge/src/main.py list
```

## Поиск агента

```bash
uv run /opt/clawforge/src/main.py search --query "<поисковый запрос>"
```

## Переключить на агента

```bash
uv run /opt/clawforge/src/main.py switch --agent <agent_name>
```

## Вернуться к оркестратору

```bash
uv run /opt/clawforge/src/main.py switch --agent orchestrator
```

## Удалить агента

ВАЖНО: Перед вызовом этой команды ОБЯЗАТЕЛЬНО запроси подтверждение у пользователя.

```bash
uv run /opt/clawforge/src/main.py delete --agent <agent_name>
```
```

**Step 2: Commit**

```bash
git add skills/
git commit -m "feat: claw-forge skill for orchestrator"
```

---

## Task 8: Setup script

**Files:**
- Create: `setup.py`

**Step 1: Implement setup.py**

```python
#!/usr/bin/env python3
"""ClawForge setup script — installs/updates/uninstalls on an OpenClaw server."""

import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
MAIN_WORKSPACE = os.path.join(OPENCLAW_HOME, "workspace")
WORKSPACES_DIR = os.path.join(OPENCLAW_HOME, "workspaces")

BASE_AGENTS = ["analyst", "developer", "tester", "validator"]


def run_cmd(cmd):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  WARN: {result.stderr.strip()}")
    return result.returncode == 0


def install():
    print("=== ClawForge Setup ===\n")

    # 1. Base agents
    for i, agent in enumerate(BASE_AGENTS, 1):
        print(f"[{i}/{len(BASE_AGENTS) + 2}] Создаю агента {agent}...")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        os.makedirs(workspace, exist_ok=True)

        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        shutil.copy2(src_soul, dst_soul)

        run_cmd(f'openclaw agents add {agent} --workspace "{workspace}" --non-interactive')
        print(f"  ✓ {agent}")

    # 2. Orchestrator SOUL.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{len(BASE_AGENTS) + 2}] Настраиваю оркестратор...")
    src_soul = os.path.join(SCRIPT_DIR, "agents", "orchestrator", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  ✓ SOUL.md оркестратора обновлён")

    # 3. Agent-forge skill
    step += 1
    print(f"[{step}/{len(BASE_AGENTS) + 2}] Устанавливаю skill claw-forge...")
    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(src_skill, dst_skill)
    print("  ✓ skill claw-forge установлен")

    # 4. Init registry
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
    import registry
    registry.init_db()
    print("  ✓ реестр инициализирован")

    print(f"\n=== ClawForge установлен! ===")
    print(f"Базовых агентов: {len(BASE_AGENTS) + 1} (orchestrator + {', '.join(BASE_AGENTS)})")
    print(f"Напишите боту в Telegram: \"какие агенты есть?\"")


def update():
    print("=== ClawForge Update ===\n")

    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        if os.path.exists(workspace):
            shutil.copy2(src_soul, dst_soul)
            print(f"  ✓ {agent} SOUL.md обновлён")

    src_soul = os.path.join(SCRIPT_DIR, "agents", "orchestrator", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  ✓ orchestrator SOUL.md обновлён")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(src_skill, dst_skill)
    print("  ✓ skill claw-forge обновлён")

    print("\n=== Обновление завершено ===")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    for agent in BASE_AGENTS:
        print(f"  Удаляю агента {agent}...")
        run_cmd(f'openclaw agents delete {agent} --yes')
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        print(f"  ✓ {agent} удалён")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)
        print("  ✓ skill claw-forge удалён")

    db_path = os.path.join(SCRIPT_DIR, "clawforge.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  ✓ реестр удалён")

    print("\n=== ClawForge удалён. OpenClaw в чистом состоянии. ===")


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

**Step 2: Commit**

```bash
git add setup.py
git commit -m "feat: setup script (install/update/uninstall)"
```

---

## Task 9: Integration test on server

**Prerequisites:** New server with OpenClaw installed and Telegram configured.

**Step 1: Deploy to server**

```bash
ssh root@<new-server-ip>
cd /opt
git clone <repo-url> clawforge
cd clawforge
python setup.py
```

Expected output:
```
=== ClawForge Setup ===
[1/6] Создаю агента analyst...    ✓
[2/6] Создаю агента developer...  ✓
[3/6] Создаю агента tester...     ✓
[4/6] Создаю агента validator...  ✓
[5/6] Настраиваю оркестратор...   ✓
[6/6] Устанавливаю skill...       ✓
=== ClawForge установлен! ===
```

**Step 2: Verify agents registered**

```bash
openclaw agents list
```

Expected: 5 agents (main/orchestrator + analyst + developer + tester + validator)

**Step 3: Test via Telegram**

Send to bot: "какие агенты есть?"
Expected: orchestrator calls claw-forge skill, runs `main.py list`, returns empty registry message.

**Step 4: Test agent creation**

Send to bot: "Создай агента который умеет анализировать тексты на тональность"
Expected: pipeline runs, new agent appears in registry and OpenClaw.

**Step 5: Test switching**

Send: "переключи на <new-agent-name>"
Expected: routing changes, now talking to new agent.

Send: "/back"
Expected: returns to orchestrator.

**Step 6: Test deletion**

Send: "удали агента <name>"
Expected: confirmation prompt → "да" → agent deleted.

**Step 7: Commit any fixes**

```bash
git add -A
git commit -m "fix: adjustments from integration testing"
```

---

## Summary

| Task | What | Estimated LOC |
|------|------|---------------|
| 1 | Scaffolding + git | ~10 |
| 2 | Registry (SQLite) | ~90 |
| 3 | Deploy (OpenClaw CLI wrapper) | ~90 |
| 4 | Orchestration (pipeline) | ~200 |
| 5 | CLI (main.py) | ~80 |
| 6 | SOUL.md x5 | ~5 files |
| 7 | SKILL.md | 1 file |
| 8 | Setup script | ~120 |
| 9 | Integration test | manual |
| **Total** | | **~580 LOC Python + 6 markdown** |
