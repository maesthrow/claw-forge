# Передача секретов в пайплайне создания агентов

**Дата:** 2026-04-05
**Статус:** Утверждён

## Проблема

При создании агента `calendario` пароль приложения Яндекс CalDAV не был
прописан в `config.json` — вместо реального значения попал плейсхолдер
`YOUR_APP_PASSWORD_HERE`. Пришлось доделывать вручную.

### Корень проблемы

В `orchestration.py` в промпте для Analyst-а было правило:
> НИКОГДА не включай токены, ключи и секреты в heartbeat_message или requirements.

Это правило было написано для одного конкретного случая — токена Telegram-бота,
который архитектурно хранится в `openclaw.json`, а не в workspace агента. Но
правило слишком общее: Analyst вырезал **любой секрет** из входного текста,
и реальное значение пароля терялось между Analyst и Developer.

В итоге:
- Analyst получил задачу с паролем в тексте
- Вырезал пароль из requirements
- Developer получил requirements без пароля → сгенерировал `config.json` с плейсхолдером
- Tester увидел ошибку подключения, но не понял что проблема в отсутствии секрета
- Пайплайн завершился с нерабочим агентом

### Что отсутствует в архитектуре

- Канал передачи секретов **в обход LLM-промптов**
- Механизм подстановки секретов в артефакты Developer-а
- Правила для Analyst/Developer как обращаться с плейсхолдерами секретов

## Решение

Architect собирает секреты из чата с пользователем, передаёт их отдельным
параметром в CLI. Секреты **никогда не попадают в LLM-промпты** — в них
используются плейсхолдеры `<SECRET:name>`. Подстановка реальных значений
происходит в Python-коде перед деплоем.

### Формат плейсхолдеров

`<SECRET:name>` где `name` — snake_case идентификатор латиницей.

Примеры: `<SECRET:caldav_password>`, `<SECRET:openai_api_key>`, `<SECRET:smtp_password>`.

### Поток данных

1. **Пользователь** пишет Architect-у: "Создай агента, пароль: XYZ"
2. **Architect** извлекает секрет, заменяет в тексте на `<SECRET:caldav_password>`, формирует JSON `{"caldav_password": "XYZ"}`
3. **Architect** вызывает skill claw-forge:
   ```
   main.py create --task "...<SECRET:caldav_password>..." --secrets '{"caldav_password":"XYZ"}' --notify telegram:ID
   ```
4. **main.py** парсит `--secrets`, передаёт в `run_pipeline(task, secrets)`
5. **Analyst/Developer/Reviewer/Tester** видят только плейсхолдеры, не знают реальных значений
6. **orchestration.py** после Reviewer approved вызывает `substitute_secrets(artifacts, secrets)` — заменяет плейсхолдеры на реальные значения
7. **Deploy** записывает артефакты с реальными значениями в workspace агента
8. Если в артефактах остался нераскрытый плейсхолдер — пайплайн падает с ошибкой

### Сценарий без секрета

Если Architect видит что задача требует секрет (например упомянут Яндекс
Календарь, CalDAV), но пользователь пароль не прислал — Architect в чате
просит его, получает, потом запускает пайплайн. Это естественное продолжение
текущей логики "задать уточняющие вопросы перед запуском".

## Изменения

### Architect (`agents/architect/SOUL.md`)

Добавить правило в секцию "Правила вызова skill" → "Шаг 2: Подтверди перед запуском":

```markdown
### Сбор секретов (перед запуском)

Перед вызовом skill claw-forge проверь: упоминал ли пользователь пароли,
токены, API-ключи, секреты для внешних сервисов (не путать с токеном
Telegram-бота — он обрабатывается отдельно после создания).

Если да:
1. Вынеси каждый секрет в отдельную пару ключ-значение, где ключ —
   snake_case имя (например `caldav_password`, `openai_api_key`),
   значение — реальный секрет
2. В описании задачи замени реальные значения на плейсхолдеры
   вида `<SECRET:имя>`
3. Передай secrets в skill отдельным параметром

Если задача требует секрет, но пользователь его не прислал — СНАЧАЛА
запроси его в чате, получи, потом запускай конвейер.

Это применяется и для создания нового агента, и для доработки существующего.
```

### Skill claw-forge (`skills/claw-forge/SKILL.md`)

Обновить команду `create`:

```bash
python3 /opt/clawforge/src/main.py create \
  --task "<описание задачи с плейсхолдерами <SECRET:name> вместо реальных секретов>" \
  --secrets '<JSON с секретами или {}>' \
  --notify telegram:{{TELEGRAM_USER_ID}}
```

С примером использования.

### main.py

1. Добавить аргумент `--secrets` в парсер `cmd_create` (default `'{}'`)
2. Парсить JSON, валидировать что это dict
3. Передавать `secrets` в `orchestration.run_pipeline()`

### orchestration.py

1. **Сигнатура** `run_pipeline(task_description, secrets=None)` — secrets по умолчанию `{}`

2. **Правила в промпте Analyst-а** (добавить в блок "Правила среды OpenClaw"):
   ```
   - Плейсхолдеры секретов: если в задаче встречаешь <SECRET:name> —
     НЕ пытайся раскрыть или угадать значение. Это указатель на внешний
     секрет. В requirements используй этот же плейсхолдер как есть.
   ```

3. **Правила в промпте Developer-а** (добавить в developer_prompt):
   ```
   Плейсхолдеры секретов: если в requirements/data_files тебе нужен
   пароль/токен/ключ — используй плейсхолдер вида <SECRET:name>
   (где name — snake_case идентификатор). НЕ подставляй placeholder-строки
   типа YOUR_PASSWORD_HERE, TODO, CHANGEME — они не будут заменены
   и агент упадёт. Только формат <SECRET:name>.
   ```

4. **Функция `substitute_secrets(artifacts, secrets)`**:
   ```python
   SECRET_PLACEHOLDER_RE = re.compile(r'<SECRET:([a-z][a-z0-9_]*)>')
   MALFORMED_PLACEHOLDER_RE = re.compile(r'<SECRET:')

   def substitute_secrets(artifacts, secrets):
       """Replace <SECRET:name> placeholders in artifacts with real values.

       Raises ValueError if placeholder found but no matching secret provided,
       or if malformed placeholders remain after substitution.
       """
       missing = set()

       def replace(text):
           if not isinstance(text, str):
               return text
           def sub(m):
               name = m.group(1)
               if name not in secrets:
                   missing.add(name)
                   return m.group(0)
               return secrets[name]
           return SECRET_PLACEHOLDER_RE.sub(sub, text)

       for key in ["soul_md", "agents_md", "identity_md"]:
           if key in artifacts:
               artifacts[key] = replace(artifacts[key])

       for nested_key in ["skills", "data_files", "scripts"]:
           if nested_key in artifacts and isinstance(artifacts[nested_key], dict):
               for fname, content in artifacts[nested_key].items():
                   artifacts[nested_key][fname] = replace(content)

       if missing:
           raise ValueError(f"Missing secrets: {', '.join(sorted(missing))}")

       # Check for malformed placeholders left unreplaced
       for key in ["soul_md", "agents_md", "identity_md"]:
           if key in artifacts and isinstance(artifacts[key], str):
               if MALFORMED_PLACEHOLDER_RE.search(artifacts[key]):
                   raise ValueError(f"Malformed secret placeholder in {key}")
       for nested_key in ["skills", "data_files", "scripts"]:
           if nested_key in artifacts and isinstance(artifacts[nested_key], dict):
               for fname, content in artifacts[nested_key].items():
                   if isinstance(content, str) and MALFORMED_PLACEHOLDER_RE.search(content):
                       raise ValueError(f"Malformed secret placeholder in {nested_key}/{fname}")

       return artifacts
   ```

5. **Вызов `substitute_secrets()` перед deploy-ем** (после reviewer approved):
   ```python
   try:
       artifacts = substitute_secrets(artifacts, secrets)
   except ValueError as e:
       return {
           "action": "rejected",
           "agent_name": requirements.get("agent_name", "?"),
           "issues": [str(e)],
           "message": (
               f"Не удалось создать агента: в артефактах остались "
               f"нераскрытые секреты ({e}). Это внутренняя ошибка пайплайна. "
               f"Попробуй создать агента заново."
           )
       }
   ```

6. **Маскировка секретов в логах** — в `log_pipeline_event()`:
   ```python
   def mask_secrets_in_text(text, secrets):
       """Replace secret values with *** in logged text.
       
       Only masks values with length >= 8 to avoid accidentally masking 
       common words that might coincide with short secrets.
       """
       if not secrets:
           return text
       for value in secrets.values():
           if value and len(value) >= 8:
               text = text.replace(value, "***")
       return text
   ```

   Применяется к `prompt` и `response` перед записью в лог. Требует чтобы
   `secrets` передавались в `log_pipeline_event` — значит добавить параметр
   и передавать из `call_agent_with_retry` / напрямую из `run_pipeline`.

   Упрощение: хранить secrets в module-level variable на время работы pipeline,
   установленной в `run_pipeline`, очищать в `finally`. Это избавляет от
   прокидывания через все слои.

## Удалить старое правило

В промпте Analyst-а (строка 286 в orchestration.py) сейчас:
> НИКОГДА не включай токены, ключи и секреты в heartbeat_message или requirements.
> Агент читает токен из openclaw.json самостоятельно.

Заменить на более точное:
> НИКОГДА не включай токен Telegram-бота в heartbeat_message или requirements —
> агент читает его из openclaw.json. Для других внешних секретов (пароли,
> API-ключи) используй плейсхолдеры <SECRET:name> как описано выше.

## Безопасность

- Секреты живут только в памяти Python-процесса (child после fork)
- Не пишутся в файлы
- Не попадают в LLM-промпты (Analyst/Developer/Reviewer/Tester видят только плейсхолдеры)
- Маскируются в `pipeline.log` (значения длиной >= 8 заменяются на `***`)
- При cancel (SIGTERM) — процесс убивается, память освобождается

## Обратная совместимость

- `--secrets` по умолчанию `'{}'` — пайплайн работает без секретов как сейчас
- Если в артефактах нет плейсхолдеров — `substitute_secrets()` просто ничего не заменяет
- Существующие агенты не ломаются

## Что НЕ меняется

- Reviewer, Tester SOUL.md — не трогаем
- Deploy — работает с уже подставленными артефактами
- Формат JSON ответов Analyst/Developer — без изменений
- Setup.py — без изменений

## Затрагиваемые файлы

- `agents/architect/SOUL.md` — правило сбора секретов перед запуском
- `skills/claw-forge/SKILL.md` — команда create с параметром --secrets
- `src/main.py` — аргумент --secrets, парсинг JSON
- `src/orchestration.py` — сигнатура run_pipeline, правила для Analyst/Developer,
  функция substitute_secrets, маскировка в логах
