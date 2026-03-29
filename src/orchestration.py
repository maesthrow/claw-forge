"""ClawForge orchestration — agent creation pipeline."""

import datetime
import json
import os
import re
import time

import deploy
import registry


PIPELINE_STEP_DELAY = 2  # seconds between pipeline steps to reduce API pressure


def update_pipeline_agent_name(agent_name):
    """Update pipeline PID file with agent_name after analyst returns."""
    pid_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "pipeline.pid")
    try:
        with open(pid_path, "r") as f:
            data = json.load(f)
        data["agent_name"] = agent_name
        with open(pid_path, "w") as f:
            json.dump(data, f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def validate_agent_name(name):
    """Validate agent name: lowercase letters, digits, underscores only."""
    if not re.match(r'^[a-z][a-z0-9_]{1,49}$', name):
        raise ValueError(f"Invalid agent name: '{name}'. Use lowercase letters, digits, underscores. Start with letter. Max 50 chars.")


def build_reviewer_prompt(requirements, artifacts, previous_soul_md=None):
    """Build reviewer prompt — static checks on artifacts."""
    extend_note = ""
    if previous_soul_md:
        extend_note = f"""
Предыдущий SOUL.md агента (до изменений):
{previous_soul_md}

Проверь: не раздулся ли SOUL.md дублями при обновлении. Если одна и та же инструкция повторяется в нескольких местах — это проблема.
"""

    return f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}
{extend_note}
Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Есть ли AGENTS.md с правилами workspace для агента?
5. Есть ли IDENTITY.md с именем, описанием и эмодзи агента?
6. Агент автономен — нет команд переключения (/main, /set, switch)?
7. Нет ли ДУБЛЕЙ — одинаковых по смыслу инструкций в разных местах SOUL.md?
8. Платформо-специфика: для Telegram не экранировать # (писать #AI, не \\#AI), parse_mode корректен?
9. YAGNI — нет лишних возможностей за рамками требований?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению"]
}}

Верни ТОЛЬКО JSON."""


def build_tester_prompt(requirements, agent_response):
    """Build tester prompt — evaluates real agent response."""
    return f"""Проверь реальный ответ агента на тестовое сообщение.

Тестовое сообщение: {requirements.get('test_message', 'не указано')}
Ожидаемое поведение: {requirements.get('expected_behavior', 'не указано')}

Реальный ответ агента:
{agent_response}

Полные требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Проверь:
1. Ответ содержит все ожидаемые элементы из expected_behavior?
2. Формат соответствует требованиям?
3. Нет заглушек, "н/д", пустых полей где должны быть данные?
4. Ответ на правильном языке?
5. Нет сообщений об ошибках или traceback?

Верни JSON:
{{
  "approved": true/false,
  "agent_response_preview": "первые 300 символов ответа",
  "issues": ["конкретные проблемы"],
  "reason": "общая оценка"
}}

Верни ТОЛЬКО JSON."""


def build_runtime_fix_prompt(artifacts, test_report, agent_response):
    """Build developer fix prompt based on real agent behavior."""
    return f"""Тестер проверил реальное поведение агента и нашёл проблемы.

Реальный ответ агента:
{agent_response[:1000]}

Проблемы от тестера: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Оценка: {test_report.get('reason', '')}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь артефакты чтобы агент отвечал корректно. Верни обновлённый JSON в том же формате.
ВАЖНО: не дублируй инструкции, делай точечные правки."""


def format_notification(deploy_result, requirements, test_report=None):
    """Format user notification with test results."""
    action = deploy_result["action"]
    name = deploy_result["agent_name"]

    if action == "created":
        if test_report and test_report.get("approved"):
            msg = f"Агент '{name}' создан и готов к работе."
        elif test_report and not test_report.get("approved"):
            msg = f"Агент '{name}' создан."
        else:
            msg = f"Агент '{name}' создан и готов к работе."
    elif action == "extended":
        msg = f"Агент '{name}' обновлён."
    elif action == "rejected":
        issues = deploy_result.get("issues", [])
        msg = f"Не удалось создать агента.\nПроблемы: {'; '.join(issues[:3])}"
        msg += "\nПопробуй уточнить задачу."
        return msg
    else:
        msg = f"Операция '{action}' завершена для '{name}'."

    if test_report and test_report.get("approved"):
        test_msg = requirements.get("test_message", "")
        if len(test_msg) > 60:
            test_msg = test_msg[:60] + "..."
        msg += f"\nТест пройден: отправил \"{test_msg}\" — ответ соответствует требованиям."
    elif test_report and not test_report.get("approved"):
        issues = test_report.get("issues", [])
        msg += f"\nТест выявил замечания: {'; '.join(issues[:2])}"
        msg += "\nМожешь проверить агента и при необходимости доработать."

    if action == "created":
        msg += "\nЕсли есть токен Telegram-бота — пришли его чтобы привязать."

    return msg


def run_pipeline(task_description):
    """Run the full creation pipeline: analyst -> developer -> reviewer -> deploy -> tester."""

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
  "agent_type": "interactive_agent" | "automation",
  "description": "описание на русском",
  "capabilities": ["capability1", "capability2"],
  "extend_agent": "имя существующего агента если decision=extend_existing, иначе null",
  "reuse_agent": "имя существующего агента если decision=reuse_existing, иначе null",
  "reference_agents": ["имена агентов для референса если есть похожие"],
  "requirements": "детальные требования для разработчика",
  "needs_heartbeat": false,
  "heartbeat_schedule": "cron выражение если needs_heartbeat=true, иначе null",
  "heartbeat_message": "сообщение для heartbeat если needs_heartbeat=true, иначе null",
  "test_message": "тестовое сообщение для проверки агента после деплоя",
  "expected_behavior": "описание ожидаемого поведения агента при получении test_message"
}}

ВАЖНО: если needs_heartbeat=true, heartbeat_message должен быть полностью консистентен с форматом сообщения описанным в requirements. Не допускай расхождений (например разный формат: одна строка vs несколько строк).

Правила среды OpenClaw (ОБЯЗАТЕЛЬНО учитывать в requirements):
- Токен Telegram-бота хранится в /root/.openclaw/openclaw.json → channels.telegram.accounts.<agent_name>.botToken. НЕ через переменные окружения.
- Файлы данных агента: абсолютные пути от /root/.openclaw/workspaces/<agent_name>/. Если файл не существует — создавать с пустой структурой, НЕ падать с ошибкой.
- Cron-задачи управляются через /root/.openclaw/cron/jobs.json (поле enabled). Агент ДОЛЖЕН управлять cron: включать при первом подписчике, выключать когда подписчиков нет.
- РАСПИСАНИЕ: если в задаче есть ЛЮБОЕ указание на расписание ("каждый день", "раз в час", "в 10:00", "ежедневно", "по утрам") — ОБЯЗАТЕЛЬНО ставь needs_heartbeat=true и заполняй heartbeat_schedule (cron-выражение, например "0 6 * * *" для ежедневно в 06:00 UTC) и heartbeat_message. Без исключений. Поддерживаемые форматы: */N * * * * (каждые N мин), 0 */N * * * (каждые N час), M H * * * (ежедневно в H:M UTC).
- Ответ пользователю — через стандартный ответ агента (OpenClaw доставит). Telegram Bot API — только для рассылки контента подписчикам.
- Взаимодействие с пользователем — через текстовые сообщения на естественном языке ("подпиши меня", "отпиши меня", "отправь новости").
- НИКОГДА не включай токены, ключи и секреты в heartbeat_message или requirements. Агент читает токен из openclaw.json самостоятельно.
- Если задача требует точных вычислений, скриншотов, обработки файлов или персистентного хранения данных — укажи в requirements что нужен exec-скрипт.
- В expected_behavior описывай формат и структуру ответа, не конкретные вычисленные значения. LLM-тестер не может верифицировать точность вычислений.
- test_message должен работать через CLI без Telegram-контекста (нет chat_id). Для агентов с подпиской тестируй запрос данных, не операции подписки.

Верни ТОЛЬКО JSON, без пояснений."""

    requirements = call_agent_with_retry("analyst", analyst_prompt)
    time.sleep(PIPELINE_STEP_DELAY)

    # Validate agent name first, then update PID file
    if requirements.get("agent_name"):
        validate_agent_name(requirements["agent_name"])
        update_pipeline_agent_name(requirements["agent_name"])

    # 3. Handle reuse case
    if requirements.get("decision") == "reuse_existing":
        return {
            "action": "reuse",
            "agent_name": requirements["reuse_agent"],
            "message": f"Для этой задачи подходит существующий агент: {requirements['reuse_agent']}"
        }

    # 4. Handle automation-only case
    if requirements.get("decision") == "automation_only":
        telegram_user_id = deploy.get_telegram_user_id()
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
    heartbeat_note = "Агент использует heartbeat — применяй правила heartbeat из своих инструкций." if requirements.get("needs_heartbeat") else ""

    # For extend: include current SOUL.md so developer can update it
    current_soul_context = ""
    if requirements.get("decision") == "extend_existing" and requirements.get("extend_agent"):
        agent_info = registry.get_agent(requirements["extend_agent"])
        if agent_info and agent_info.get("workspace_path"):
            soul_path = os.path.join(agent_info["workspace_path"], "SOUL.md")
            try:
                with open(soul_path, "r", encoding="utf-8") as f:
                    current_soul_context = f"\nТекущий SOUL.md агента (обнови его, не пиши с нуля):\n{f.read()}\n"
            except FileNotFoundError:
                pass

    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_soul_context}
Сгенерируй конфигурацию агента по своим инструкциям.
{heartbeat_note}
Если задача требует исполняемых скриптов — добавь их в поле "scripts".
Если скрипты требуют системных зависимостей — добавь их в поле "system_deps".

Верни ТОЛЬКО JSON."""

    artifacts = call_agent_with_retry("developer", developer_prompt)
    time.sleep(PIPELINE_STEP_DELAY)

    # 6. Reviewer — static checks (up to 3 retries)
    # Save previous SOUL.md for extend comparison
    previous_soul_md = None
    if current_soul_context:
        previous_soul_md = current_soul_context

    max_reviewer_retries = 3
    for reviewer_attempt in range(max_reviewer_retries + 1):
        review = call_agent_with_retry("reviewer",
            build_reviewer_prompt(requirements, artifacts, previous_soul_md))
        time.sleep(PIPELINE_STEP_DELAY)

        if review.get("approved", False):
            break

        if reviewer_attempt < max_reviewer_retries:
            fix_prompt = f"""Ревьюер нашёл проблемы в артефактах.

Проблемы: {json.dumps(review.get('issues', []), ensure_ascii=False)}
Предложения: {json.dumps(review.get('fixes', []), ensure_ascii=False)}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь и верни обновлённый JSON в том же формате.
ВАЖНО: не дублируй инструкции, агент должен быть автономным."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            time.sleep(PIPELINE_STEP_DELAY)
            continue

        reviewer_issues = review.get("issues", ["неизвестная проблема"])
        return {
            "action": "rejected",
            "agent_name": requirements.get("agent_name", "?"),
            "issues": reviewer_issues,
            "message": format_notification(
                {"action": "rejected", "agent_name": requirements.get("agent_name", "?"), "issues": reviewer_issues},
                requirements
            )
        }

    # 7. Deploy
    agent_name = requirements["agent_name"]

    if requirements.get("decision") == "extend_existing":
        deploy_result = deploy_extension(requirements, artifacts)
    else:
        deploy_result = deploy_new_agent(requirements, artifacts)

    # Install scripts and system deps
    if artifacts.get("scripts"):
        deploy.install_scripts(agent_name if requirements.get("decision") != "extend_existing"
                               else requirements["extend_agent"], artifacts["scripts"])
    if artifacts.get("system_deps"):
        deploy.install_system_deps(artifacts["system_deps"])

    # 8. Tester — real agent run (up to 2 retries)
    test_message = requirements.get("test_message")
    test_report = None
    actual_agent = requirements.get("extend_agent") if requirements.get("decision") == "extend_existing" else agent_name

    if test_message:
        max_tester_retries = 2
        for tester_attempt in range(max_tester_retries + 1):
            try:
                agent_response = deploy.call_agent(actual_agent, test_message)
                # Strip OpenClaw system prefixes (e.g. "[agents/auth-profiles] inherited ...")
                agent_response = re.sub(r'^\[agents/[^\]]*\][^\n]*\n?', '', agent_response).strip()
            except RuntimeError as e:
                agent_response = f"Ошибка вызова агента: {str(e)[:300]}"

            test_report = call_agent_with_retry("tester",
                build_tester_prompt(requirements, agent_response))
            time.sleep(PIPELINE_STEP_DELAY)

            if test_report.get("approved", False):
                break

            if tester_attempt < max_tester_retries:
                # Developer fixes based on real response
                artifacts = call_agent_with_retry("developer",
                    build_runtime_fix_prompt(artifacts, test_report, agent_response))
                time.sleep(PIPELINE_STEP_DELAY)

                # Reviewer re-checks
                review = call_agent_with_retry("reviewer",
                    build_reviewer_prompt(requirements, artifacts, previous_soul_md))
                time.sleep(PIPELINE_STEP_DELAY)

                # Re-deploy updated artifacts
                deploy.update_agent_files(
                    name=actual_agent,
                    soul_md=artifacts.get("soul_md"),
                    agents_md=artifacts.get("agents_md"),
                    identity_md=artifacts.get("identity_md"),
                    skills=artifacts.get("skills"),
                    data_files=artifacts.get("data_files"),
                    scripts=artifacts.get("scripts")
                )
                if artifacts.get("scripts"):
                    deploy.install_scripts(actual_agent, artifacts["scripts"])
                continue

    # 9. Format notification with test results
    deploy_result["message"] = format_notification(deploy_result, requirements, test_report)
    return deploy_result


def deploy_extension(requirements, artifacts):
    """Full update of an existing agent: files, skills, data, heartbeat, registry."""
    target_agent = requirements["extend_agent"]

    # Update all agent files (only writes provided ones)
    deploy.update_agent_files(
        name=target_agent,
        soul_md=artifacts.get("soul_md"),
        agents_md=artifacts.get("agents_md"),
        identity_md=artifacts.get("identity_md"),
        skills=artifacts.get("skills"),
        data_files=artifacts.get("data_files"),
        scripts=artifacts.get("scripts")
    )

    # Update or create heartbeat (same name as create — idempotent)
    heartbeat_note = ""
    if requirements.get("needs_heartbeat"):
        try:
            telegram_user_id = deploy.get_telegram_user_id()
            deploy.add_heartbeat(
                name=target_agent,
                cron_expr=requirements["heartbeat_schedule"],
                agent_name=target_agent,
                message=requirements["heartbeat_message"],
                telegram_user_id=telegram_user_id
            )
        except Exception as e:
            heartbeat_note = f" Heartbeat не обновлён: {str(e)[:200]}"

    # Update registry
    existing_agent = registry.get_agent(target_agent)
    if existing_agent:
        new_caps = list(set(existing_agent["capabilities"] + requirements["capabilities"]))
        registry.update_agent(target_agent, capabilities=new_caps,
                              description=requirements["description"])

    return {
        "action": "extended",
        "agent_name": target_agent,
        "needs_heartbeat": requirements.get("needs_heartbeat", False),
        "message": f"Агент '{target_agent}' обновлён.{heartbeat_note}"
    }


def deploy_new_agent(requirements, artifacts):
    """Deploy a brand new agent to OpenClaw."""
    agent_name = requirements["agent_name"]

    workspace = deploy.create_agent_workspace(
        name=agent_name,
        soul_md=artifacts["soul_md"],
        agents_md=artifacts.get("agents_md"),
        identity_md=artifacts.get("identity_md"),
        skills=artifacts.get("skills", {}),
        data_files=artifacts.get("data_files"),
        scripts=artifacts.get("scripts")
    )
    deploy.register_agent(agent_name, workspace)

    registry.add_agent(
        name=agent_name,
        agent_type=requirements["agent_type"],
        description=requirements["description"],
        capabilities=requirements["capabilities"],
        workspace_path=workspace
    )

    heartbeat_note = ""
    if requirements.get("needs_heartbeat"):
        try:
            telegram_user_id = deploy.get_telegram_user_id()
            deploy.add_heartbeat(
                name=agent_name,
                cron_expr=requirements["heartbeat_schedule"],
                agent_name=agent_name,
                message=requirements["heartbeat_message"],
                telegram_user_id=telegram_user_id
            )
        except Exception as e:
            heartbeat_note = f" Heartbeat не создан: {str(e)[:200]}"

    return {
        "action": "created",
        "agent_name": agent_name,
        "needs_heartbeat": requirements.get("needs_heartbeat", False),
        "message": f"Агент '{agent_name}' создан и готов к работе.{heartbeat_note}"
    }



def format_registry_for_prompt(agents):
    """Format agent list for inclusion in LLM prompts."""
    if not agents:
        return "Реестр пуст — агентов пока нет."
    lines = []
    for a in agents:
        lines.append(f"- {a['name']} ({a['type']}): {a['description']}. Capabilities: {', '.join(a['capabilities'])}")
    return "\n".join(lines)


def parse_json_response(response):
    """Extract JSON from LLM response, handling markdown code blocks and extra text."""
    text = response.strip()

    # 1. Try direct parse first (handles clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # "Extra data" = valid JSON + garbage after it (extra }, trailing text)
        # Python tells us exactly where the valid JSON ends — use that position
        if e.msg == 'Extra data' and e.pos > 0:
            try:
                return json.loads(text[:e.pos])
            except (json.JSONDecodeError, ValueError):
                pass
    except ValueError:
        pass

    # 2. Try finding JSON boundaries in original text (handles extra data after JSON,
    #    and JSON with backticks inside values that would break code block stripping)
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start != -1:
            end = text.rfind(end_char)
            if end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue

    # 3. Try stripping markdown code blocks (for responses wrapped in ```)
    stripped = text
    if "```json" in stripped:
        stripped = stripped.split("```json")[1].split("```")[0]
    elif "```" in stripped:
        stripped = stripped.split("```")[1].split("```")[0]

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

    return json.loads(text)


def is_api_error(response):
    """Detect OpenClaw API errors (rate limit, timeouts) vs actual LLM responses."""
    if not response:
        return True
    text = response.strip()
    if text.startswith("\u26a0\ufe0f"):
        return True
    # Only check markers on short responses — LLM JSON can contain these phrases in content
    if len(text) < 200:
        api_markers = ["rate limit", "try again later", "connection refused", "service unavailable"]
        return any(m in text.lower() for m in api_markers)
    return False


def _call_with_api_retry(agent_name, prompt, max_retries=4):
    """Call agent, retrying on API errors with exponential backoff.

    Raises RuntimeError if all retries exhausted on API error —
    prevents useless JSON retries when the problem is rate limiting.
    """
    for attempt in range(max_retries + 1):
        response = deploy.call_agent(agent_name, prompt)
        if not is_api_error(response):
            return response
        if attempt < max_retries:
            delay = 5 * (3 ** attempt)  # 5s, 15s, 45s, 135s
            log_pipeline_event(
                agent_name, "api_retry", response,
                f"api_error attempt {attempt + 1}/{max_retries}, waiting {delay}s"
            )
            time.sleep(delay)
    log_pipeline_event(
        agent_name, "api_retry", response,
        f"api_error all {max_retries} retries exhausted"
    )
    raise RuntimeError(f"Agent {agent_name}: API error after {max_retries} retries — {response[:200]}")


def call_agent_with_retry(agent_name, prompt, max_retries=2):
    """Call agent and parse JSON response.

    Two-phase retry:
    - Phase 1: API-level retry with backoff (rate limit, timeouts) — handled by _call_with_api_retry
    - Phase 2: JSON-level retry with explicit instruction (LLM returned non-JSON)
    """
    response = _call_with_api_retry(agent_name, prompt)
    log_pipeline_event(agent_name, prompt, response, "ok")

    try:
        return parse_json_response(response)
    except (json.JSONDecodeError, ValueError) as e:
        log_pipeline_event(agent_name, prompt, response, f"parse_error: {e}")

    # Retry with explicit JSON instruction
    for attempt in range(max_retries):
        retry_prompt = (
            f"Предыдущий ответ не удалось распарсить как JSON. "
            f"Верни ТОЛЬКО валидный JSON без какого-либо текста до или после. "
            f"Никаких пояснений, только JSON.\n\n"
            f"Исходный запрос:\n{prompt}"
        )
        response = _call_with_api_retry(agent_name, retry_prompt)
        log_pipeline_event(agent_name, f"retry_{attempt + 1}", response, "retry")

        try:
            return parse_json_response(response)
        except (json.JSONDecodeError, ValueError):
            continue

    raise ValueError(f"Agent {agent_name} failed to return valid JSON after {max_retries} retries")


def log_pipeline_event(agent_name, prompt, response, status):
    """Log pipeline events to file."""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "pipeline.log")

    timestamp = datetime.datetime.now().isoformat()
    prompt_short = prompt[:200].replace('\n', ' ')
    response_short = response[:500].replace('\n', ' ')

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] agent={agent_name} status={status}\n")
        f.write(f"  prompt: {prompt_short}\n")
        f.write(f"  response: {response_short}\n\n")
