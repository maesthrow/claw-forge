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
4. Есть ли AGENTS.md с правилами workspace для агента?
5. Есть ли IDENTITY.md с именем, описанием и эмодзи агента?
6. Агент автономен — нет команд переключения (/main, /set, switch)?

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

ВАЖНО: если needs_heartbeat=true, heartbeat_message должен быть полностью консистентен с форматом сообщения описанным в requirements. Не допускай расхождений (например разный формат: одна строка vs несколько строк).

Правила среды OpenClaw (ОБЯЗАТЕЛЬНО учитывать в requirements):
- Токен Telegram-бота хранится в /root/.openclaw/openclaw.json → channels.telegram.accounts.<agent_name>.botToken. НЕ через переменные окружения.
- Файлы данных агента: абсолютные пути от /root/.openclaw/workspaces/<agent_name>/. Если файл не существует — создавать с пустой структурой, НЕ падать с ошибкой.
- Cron-задачи управляются через /root/.openclaw/cron/jobs.json (поле enabled). Агент ДОЛЖЕН управлять cron: включать при первом подписчике, выключать когда подписчиков нет.
- Ответ пользователю — через стандартный ответ агента (OpenClaw доставит). Telegram Bot API — только для рассылки контента подписчикам.
- Взаимодействие с пользователем — через текстовые сообщения на естественном языке ("подпиши меня", "отпиши меня", "отправь новости").
- НИКОГДА не включай токены, ключи и секреты в heartbeat_message или requirements. Агент читает токен из openclaw.json самостоятельно.

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
    reference_context = build_reference_context(requirements)

    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

{reference_context}

Сгенерируй конфигурацию OpenClaw-агента. Верни JSON:
{{
  "soul_md": "полный текст SOUL.md",
  "agents_md": "полный текст AGENTS.md",
  "identity_md": "полный текст IDENTITY.md",
  "skills": {{
    "skill-name": "полный текст SKILL.md для каждого навыка"
  }},
  "data_files": {{
    "filename.json": "начальное содержимое файла"
  }}
}}

Требования к SOUL.md:
- Чёткая роль и экспертиза агента
- Инструкции по взаимодействию с пользователем
- Границы компетенций
- Язык общения — русский
- При первом сообщении — кратко представиться
- Агент ПОЛНОСТЬЮ автономный, работает через своего Telegram-бота
- НЕ добавляй команды /main, /set, /back или переключение на других агентов
- НЕ добавляй вызовы python3 или switch

Требования к AGENTS.md:
- Стартовый протокол: при начале сессии прочитай SOUL.md
- Правила workspace агента
- Стиль общения и формат ответов
- Границы: что агент НЕ должен делать

Требования к IDENTITY.md:
- name: имя агента на русском
- description: одно предложение о роли
- emoji: подходящий эмодзи
- vibe: стиль общения (sharp/warm/calm/etc)

Требования к skills (SKILL.md):
- YAML frontmatter (name, description) + markdown body
- Описание конкретное и полезное

Правила для агентов с heartbeat/cron (если needs_heartbeat=true):
- Workspace агента: /root/.openclaw/workspaces/{requirements.get('agent_name', '<agent_name>')}/
- Пути к любым файлам агента (данные, состояние) ВСЕГДА абсолютные от workspace
- Токен Telegram-бота НЕ через env-переменную — он хранится в openclaw.json, агент не должен его читать или использовать напрямую
- Ответ пользователю — через стандартный текстовый ответ агента. OpenClaw сам доставит его в Telegram
- Взаимодействие с пользователем — через текстовые сообщения на естественном языке ("подпиши меня на рассылку", "отпиши меня", "отправь новости")
- Cron должен управляться агентом: первый подписчик → включить cron, последний отписался → выключить (через поле enabled в /root/.openclaw/cron/jobs.json). После изменения enabled ОБЯЗАТЕЛЬНО выполнить команду: openclaw gateway restart — иначе gateway не подхватит изменение
- При heartbeat: если список подписчиков/получателей пуст — завершить сессию без обработки и без LLM-вызовов
- При ошибке отправки (403 Forbidden / бот заблокирован) — автоматически удалять подписчика из списка
- Все файлы данных (subscribers.json, sent_news.json и т.д.) ОБЯЗАТЕЛЬНО указать в data_files с начальным содержимым — они создаются при deploy. Без этого агент упадёт при первом запуске (ENOENT)

Верни ТОЛЬКО JSON."""

    artifacts = call_agent_with_retry("developer", developer_prompt)
    time.sleep(PIPELINE_STEP_DELAY)

    # 6. Tester + Validator cycle with retry
    max_tester_retries = 3
    max_validator_retries = 1

    for validator_attempt in range(max_validator_retries + 1):
        # Tester — uses fresh prompt with current artifacts
        test_report = call_agent_with_retry("tester", build_tester_prompt(requirements, artifacts))
        time.sleep(PIPELINE_STEP_DELAY)

        # Tester reject → developer fix (max retries)
        tester_retries = 0
        while not test_report.get("approved", False) and tester_retries < max_tester_retries:
            fix_prompt = f"""Тестировщик нашёл проблемы в артефактах.

Проблемы: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Предложения: {json.dumps(test_report.get('fixes', []), ensure_ascii=False)}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь и верни обновлённый JSON в том же формате.
ВАЖНО: агент должен быть автономным, без команд переключения."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            time.sleep(PIPELINE_STEP_DELAY)
            test_report = call_agent_with_retry("tester", build_tester_prompt(requirements, artifacts))
            time.sleep(PIPELINE_STEP_DELAY)
            tester_retries += 1

        if not test_report.get("approved", False):
            return {
                "action": "rejected",
                "reason": f"Тестировщик не одобрил после {max_tester_retries} попыток исправления.",
                "message": "Не удалось создать агента: тестировщик нашёл неисправимые проблемы."
            }

        # Validator — uses fresh prompt with current artifacts and test report
        validation = call_agent_with_retry("validator", build_validator_prompt(requirements, artifacts, test_report))

        if validation.get("approved", False):
            break

        time.sleep(PIPELINE_STEP_DELAY)

        # Validator rejected → retry with fix
        if validator_attempt < max_validator_retries:
            fix_prompt = f"""Валидатор отклонил агента.

Причина: {validation.get('reason', 'не указана')}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь причину отказа и верни обновлённый JSON в том же формате.
ВАЖНО: агент должен быть автономным, без команд переключения."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            time.sleep(PIPELINE_STEP_DELAY)
            continue

        return {
            "action": "rejected",
            "reason": validation.get("reason", "Валидатор отклонил"),
            "message": f"Не удалось создать агента: {validation.get('reason')}. Попробуйте уточнить задачу."
        }

    # 7. Deploy
    agent_name = requirements["agent_name"]

    if requirements.get("decision") == "extend_existing":
        return deploy_extension(requirements, artifacts)
    else:
        return deploy_new_agent(requirements, artifacts)


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
        telegram_user_id = deploy.get_telegram_user_id()
        deploy.add_heartbeat(
            name=f"{target_agent}-{agent_name}",
            cron_expr=requirements["heartbeat_schedule"],
            agent_name=target_agent,
            message=requirements["heartbeat_message"],
            telegram_user_id=telegram_user_id
        )

    # Update capabilities and description in registry
    existing_agent = registry.get_agent(target_agent)
    if existing_agent:
        old_caps = existing_agent["capabilities"]
        new_caps = list(set(old_caps + requirements["capabilities"]))
        registry.update_agent(target_agent, capabilities=new_caps,
                              description=requirements["description"])

    action_msg = "обновлён" if artifacts.get("soul_md") else "расширен: добавлены новые навыки"
    return {
        "action": "extended",
        "agent_name": target_agent,
        "message": f"Агент '{target_agent}' {action_msg}."
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
        data_files=artifacts.get("data_files")
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
                name=f"{agent_name}-heartbeat",
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


def build_reference_context(requirements):
    """Load static SOUL.md structure template for the developer."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "soul_structure.md")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f"\n\n{f.read()}"
    except FileNotFoundError:
        return ""


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
