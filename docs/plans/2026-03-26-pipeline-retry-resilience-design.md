# Pipeline Retry Resilience

## Проблема

`call_agent_with_retry` не различает API-ошибки (rate limit, таймауты) и невалидный JSON от LLM. Когда OpenClaw возвращает `⚠️ API rate limit reached. Please try again later.`, пайплайн пытается парсить это как JSON, тратит JSON-ретраи на повторную отправку того же промпта — и тоже получает rate limit.

## Решение

Scope: разделение типов ошибок + экспоненциальный backoff для API + превентивная задержка между шагами.

### 1. Детекция API-ошибок — `is_api_error(response)`

Файл: `orchestration.py`

```python
def is_api_error(response):
    text = response.strip()
    if text.startswith("⚠️"):
        return True
    api_markers = ["rate limit", "try again later", "connection refused", "service unavailable"]
    return any(m in text.lower() for m in api_markers)
```

Два слоя: эмодзи-префикс (текущий формат OpenClaw) + текстовые маркеры (страховка).

### 2. API-retry с backoff — `_call_with_api_retry()`

Файл: `orchestration.py`

- Оборачивает каждый вызов `deploy.call_agent()`
- До 5 попыток при API-ошибках
- Экспоненциальный backoff: 5s → 15s → 45s → 135s → 405s
- Логирует как `api_error` с номером попытки
- Если все попытки исчерпаны — возвращает последний ответ (parse_json_response выбросит ошибку)

### 3. Переработка `call_agent_with_retry()`

Файл: `orchestration.py`

Разделение на фазы:
1. Вызов агента через `_call_with_api_retry()` (API-ретраи)
2. Парсинг JSON
3. JSON-retry с "верни ТОЛЬКО JSON" (до 2 попыток), каждый через `_call_with_api_retry()`

API-retry оборачивает каждый вызов — и первичный, и JSON-retry.

### 4. Задержка между шагами пайплайна

Файл: `orchestration.py`

```python
PIPELINE_STEP_DELAY = 2  # секунды
```

`time.sleep(PIPELINE_STEP_DELAY)` между: analyst → developer → tester → validator, а также в fix-циклах.

### 5. Логирование

- API-ошибки: `status=api_error attempt N/5, waiting Xs`
- Остальное без изменений: `ok`, `parse_error`, `retry`

## Затрагиваемые файлы

- `src/orchestration.py` — все изменения
- Добавить `import time`

## Не меняется

- `src/deploy.py` — `call_agent()` и `run_cmd()` остаются как есть
- `parse_json_response()` — без изменений
- Формат pipeline.log — тот же, новые значения status
