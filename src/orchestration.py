"""ClawForge orchestration — agent creation pipeline."""

import json
import os

import deploy
import registry


def run_pipeline(task_description):
    """Run the full creation pipeline: analyst -> developer -> tester -> validator -> deploy."""

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
  "extend_agent": "имя существующего агента если decision=extend_existing, иначе null",
  "reuse_agent": "имя существующего агента если decision=reuse_existing, иначе null",
  "reference_agents": ["имена агентов для референса если есть похожие"],
  "requirements": "детальные требования для разработчика",
  "needs_heartbeat": false,
  "heartbeat_schedule": "cron выражение если needs_heartbeat=true, иначе null",
  "heartbeat_message": "сообщение для heartbeat если needs_heartbeat=true, иначе null"
}}

Верни ТОЛЬКО JSON, без пояснений."""

    analyst_response = deploy.call_agent("analyst", analyst_prompt)
    requirements = parse_json_response(analyst_response)

    # 3. Handle reuse case
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
    reference_context = build_reference_context(requirements)

    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

{reference_context}

Сгенерируй конфигурацию OpenClaw-агента. Верни JSON:
{{
  "soul_md": "полный текст SOUL.md",
  "agents_md": "полный текст AGENTS.md или null",
  "skills": {{
    "skill-name": "полный текст SKILL.md для каждого навыка"
  }}
}}

Требования к SOUL.md:
- Чёткая роль и экспертиза агента
- Инструкции по взаимодействию с пользователем
- Границы компетенций
- Инструкция: если пользователь пишет "назад", "/back", "вернись" — выполни: python3 /opt/clawforge/src/main.py switch --agent orchestrator

Требования к skills (SKILL.md):
- YAML frontmatter (name, description) + markdown body
- Описание конкретное и полезное

Верни ТОЛЬКО JSON."""

    developer_response = deploy.call_agent("developer", developer_prompt)
    artifacts = parse_json_response(developer_response)

    # 6. Tester: validate artifacts
    tester_prompt = f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Если нужен heartbeat — есть ли конфигурация?
5. Есть ли инструкция по /back?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению"]
}}

Верни ТОЛЬКО JSON."""

    tester_response = deploy.call_agent("tester", tester_prompt)
    test_report = parse_json_response(tester_response)

    # 7. If tester found issues, send back to developer
    if not test_report.get("approved", False):
        fix_prompt = f"""Тестировщик нашёл проблемы в артефактах.

Проблемы: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Предложения: {json.dumps(test_report.get('fixes', []), ensure_ascii=False)}

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

Верни JSON:
{{
  "approved": true/false,
  "reason": "причина"
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
        return deploy_extension(requirements, artifacts)
    else:
        return deploy_new_agent(requirements, artifacts)


def deploy_extension(requirements, artifacts):
    """Deploy skill/heartbeat extension to an existing agent."""
    target_agent = requirements["extend_agent"]
    agent_name = requirements["agent_name"]

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


def deploy_new_agent(requirements, artifacts):
    """Deploy a brand new agent to OpenClaw."""
    agent_name = requirements["agent_name"]

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


def build_reference_context(requirements):
    """Load SOUL.md from reference agents for the developer."""
    context = ""
    for ref_name in requirements.get("reference_agents", []):
        ref_agent = registry.get_agent(ref_name)
        if ref_agent and ref_agent.get("workspace_path"):
            soul_path = os.path.join(ref_agent["workspace_path"], "SOUL.md")
            try:
                with open(soul_path, "r", encoding="utf-8") as f:
                    context += f"\n\n--- SOUL.md агента {ref_name} (для референса) ---\n{f.read()}"
            except FileNotFoundError:
                pass
    return context


def format_registry_for_prompt(agents):
    """Format agent list for inclusion in LLM prompts."""
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
    """Get Telegram user ID from environment."""
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
