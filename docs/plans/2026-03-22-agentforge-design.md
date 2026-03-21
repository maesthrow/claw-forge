# ClawForge — Design Document

> Система автоматического создания, управления и оркестрации AI-агентов на базе OpenClaw.

**Дата:** 2026-03-22
**Статус:** Draft
**Автор:** Дмитрий + Claude

---

## 1. Проблема

Нужна система, которая:
- Принимает текстовое описание задачи от пользователя
- Автоматически проектирует и создаёт нового AI-агента
- Добавляет его в команду
- Позволяет повторно использовать уже созданных агентов
- Поддерживает self-expansion (саморасширение)
- Может создавать агентов, автоматизации и навыки

## 2. Решение

ClawForge — тонкая Python-надстройка над OpenClaw, реализующая конвейер создания агентов и оркестрацию команды.

### Принцип

- **OpenClaw делает 95%** — агенты, LLM, Telegram, память, сессии, heartbeats, skills
- **Python CLI делает 5%** — конвейер создания, реестр, оркестрация вызовов между агентами

### Ключевое решение

Все агенты (и базовые, и создаваемые) — OpenClaw-агенты единого формата (SOUL.md + Skills + Memory). Python-слой вызывает их через `openclaw agent --agent <name> --message "..."` и управляет порядком вызовов.

## 3. Архитектура

```
┌─────────────────────────────────────────────────────────┐
│                    СЕРВЕР (Ubuntu)                       │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              OpenClaw Gateway                    │    │
│  │                                                  │    │
│  │  Telegram ←──→ Роутинг ←──→ Агенты              │    │
│  │                                                  │    │
│  │  Базовые:                                        │    │
│  │    orchestrator (default) ← точка входа          │    │
│  │    analyst                                       │    │
│  │    developer                                     │    │
│  │    tester                                        │    │
│  │    validator                                     │    │
│  │                                                  │    │
│  │  Созданные:                                      │    │
│  │    resume-scorer, price-watcher, ...             │    │
│  │                                                  │    │
│  │  LLM: GPT-5.4 (OpenAI Plus, $0)                 │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │ exec                           │
│  ┌──────────────────────▼───────────────────────────┐    │
│  │           Python CLI (/opt/clawforge/)           │    │
│  │                                                   │    │
│  │  main.py            ← точка входа CLI             │    │
│  │  orchestration.py   ← конвейер вызовов агентов    │    │
│  │  registry.py        ← реестр агентов (SQLite)     │    │
│  │  deploy.py          ← создание/удаление агентов   │    │
│  └───────────────────────────────────────────────────┘    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Связка OpenClaw ↔ Python

Orchestrator (OpenClaw-агент) имеет skill `claw-forge`, который вызывает Python CLI через `exec`. Это нативный механизм OpenClaw — агент читает SKILL.md и выполняет bash-команды.

```
Пользователь (Telegram)
  → OpenClaw Gateway
    → Orchestrator
      → обычный вопрос → отвечает сам (GPT-5.4)
      → "создай агента" → skill claw-forge → exec: python main.py create ...
      → "переключи на X" → skill claw-forge → exec: python main.py switch ...
      → "какие агенты?" → skill claw-forge → exec: python main.py list
      → "удали агента X" → запрос подтверждения → skill → exec: python main.py delete ...
```

## 4. Агенты

### 4.1 Базовые агенты (предустановлены)

| Агент | Роль | Когда вызывается |
|---|---|---|
| **orchestrator** | Точка входа, общение с пользователем, принятие решений | Всегда (default агент) |
| **analyst** | Анализ задачи, формирование требований | Первый в конвейере создания |
| **developer** | Генерация конфигураций (SOUL.md, skills, heartbeats) | После аналитика |
| **tester** | Проверка артефактов на соответствие требованиям | После разработчика |
| **validator** | Финальное одобрение / отклонение | Последний в конвейере |

Каждый базовый агент — полноценный OpenClaw-агент со своим workspace, SOUL.md, памятью и сессиями.

### 4.2 Создаваемые агенты

Результат работы конвейера. Три типа:

| Тип | Что создаётся | Пример |
|---|---|---|
| **Интерактивный агент** | SOUL.md + AGENTS.md + skills + memory | Агент для оценки резюме |
| **Автоматизация** | Heartbeat (cron) для существующего или нового агента | Ежечасная проверка цен |
| **Навык (skill)** | Skill для существующего агента | Новый навык для resume-scorer |

### 4.3 Self-expansion

Реестр растёт с каждой решённой задачей. При новом запросе:

1. Аналитик получает список существующих агентов и их capabilities из реестра
2. Решает: создать нового, расширить существующего, или предложить пользователю уже готового
3. Если создаёт нового — использует опыт существующих (паттерны, SOUL.md, skills) как основу

## 5. Потоки взаимодействия

### 5.1 Создание нового агента

```
Пользователь: "Мне нужен агент для оценки резюме"

Orchestrator: уточняющие вопросы → получает ответы
Orchestrator: "Создаю агента..."
  → exec: python main.py create --task "..."
    → SELECT FROM registry — проверка существующих
    → openclaw agent --agent analyst --message "..."       → требования (JSON)
    → openclaw agent --agent developer --message "..."     → артефакты (файлы)
    → openclaw agent --agent tester --message "..."        → отчёт проверки
    → openclaw agent --agent validator --message "..."     → APPROVED
    → mkdir workspace + записать файлы
    → openclaw agents add resume-scorer --workspace ...
    → INSERT INTO registry
  ← "Агент resume-scorer создан"

Orchestrator: "Готово! Агент Resume Scorer создан.
              Напиши 'переключи на resume-scorer' чтобы начать."
```

### 5.2 Расширение существующего агента

```
Пользователь: "Хочу чтобы resume-scorer ещё отчёты умел выгружать"

Orchestrator → exec: python main.py create --task "..."
  → SELECT FROM registry — находит resume-scorer
  → analyst: "расширить resume-scorer, добавить skill отчётов"
  → developer: генерирует новый skill
  → tester → validator → APPROVED
  → копирует skill в workspace resume-scorer
  → UPDATE registry
← "resume-scorer расширен: добавлен навык отчётов"
```

### 5.3 Переключение между агентами

```
Пользователь: "переключи на resume-scorer"
  → exec: python main.py switch --agent resume-scorer
    → openclaw agents bind --agent resume-scorer --bind telegram:<user_id>
  ← "переключено"
Orchestrator: "Ты теперь говоришь с Resume Scorer."

[прямой диалог с resume-scorer через OpenClaw]

Пользователь: "назад" / "/back"
  → exec: python main.py switch --agent orchestrator
Orchestrator: "С возвращением!"
```

### 5.4 Автоматизация

```
Пользователь: "Каждое утро в 9:00 присылай курс доллара"

Orchestrator → exec: python main.py create --task "..."
  → analyst: "простая автоматизация, агент не нужен"
  → openclaw cron add --name morning-usd --cron "0 9 * * *" \
      --agent orchestrator --message "Пришли курс USD/RUB" \
      --deliver telegram:<user_id>
  → INSERT INTO registry (type: "automation")
← "автоматизация создана"
```

### 5.5 Удаление агента

```
Пользователь: "удали агента price-watcher"

Orchestrator: "Удалить агента price-watcher
              (мониторинг цен, 2 навыка, 1 автоматизация)?
              Это действие необратимо. Подтверди: да/нет"

Пользователь: "да"

  → exec: python main.py delete --agent price-watcher
    → openclaw agents delete price-watcher
    → rm -rf workspace
    → DELETE FROM registry
  ← "удалён"

Orchestrator: "Агент price-watcher удалён."
```

### 5.6 Переиспользование (self-expansion в действии)

```
Пользователь: "Нужен агент для мониторинга цен на отели"

Orchestrator → exec: python main.py create --task "..."
  → SELECT FROM registry WHERE capabilities LIKE '%мониторинг%цен%'
  → Найден: price-watcher (мониторинг цен на авиабилеты)
  → analyst: "Есть price-watcher. Домен другой (отели vs билеты).
              Рекомендую: новый агент hotel-watcher,
              но на основе паттернов price-watcher."
  → developer получает SOUL.md price-watcher как референс
    → генерирует hotel-watcher с адаптированным SOUL.md и skills
  → tester → validator → deploy
← "hotel-watcher создан (на основе опыта price-watcher)"
```

## 6. Файловая структура проекта

### Репозиторий (разработка)

```
d:\dev\ClawForge\
├── src/
│   ├── main.py              ← точка входа CLI
│   ├── orchestration.py     ← конвейер вызовов агентов
│   ├── registry.py          ← SQLite реестр
│   └── deploy.py            ← создание/удаление в OpenClaw
│
├── agents/
│   ├── orchestrator/
│   │   └── SOUL.md
│   ├── analyst/
│   │   └── SOUL.md
│   ├── developer/
│   │   └── SOUL.md
│   ├── tester/
│   │   └── SOUL.md
│   └── validator/
│       └── SOUL.md
│
├── skills/
│   └── claw-forge/
│       └── SKILL.md
│
├── setup.py                 ← установка / обновление / удаление
└── README.md
```

### На сервере (после установки)

```
/opt/clawforge/              ← git clone репозитория
├── src/
├── agents/
├── skills/
├── setup.py
└── clawforge.db             ← SQLite (создаётся при setup)

/root/.openclaw/
├── workspace/                ← workspace orchestrator'а
│   ├── SOUL.md               ← наш SOUL.md
│   └── skills/
│       └── claw-forge/      ← наш skill
│           └── SKILL.md
│
├── workspaces/
│   ├── analyst/              ← базовый
│   ├── developer/            ← базовый
│   ├── tester/               ← базовый
│   ├── validator/            ← базовый
│   ├── resume-scorer/        ← созданный
│   └── price-watcher/        ← созданный
│
├── agents/                   ← состояние агентов (OpenClaw)
│   ├── main/                 ← orchestrator (default)
│   ├── analyst/
│   ├── developer/
│   ├── tester/
│   ├── validator/
│   ├── resume-scorer/
│   └── price-watcher/
│
└── openclaw.json
```

## 7. Стек технологий

| Компонент | Технология |
|---|---|
| AI-агенты, LLM, память, сессии | OpenClaw Gateway |
| LLM | GPT-5.4 через OpenAI Plus ($0) |
| Канал доставки | Telegram (через OpenClaw) |
| Оркестрация конвейера | Python CLI |
| Реестр агентов | SQLite |
| Деплой | SSH + git clone + setup.py |
| Сервер | Ubuntu (отдельный, чистый) |

## 8. Установка и деплой

```bash
# На новом сервере:
npm install -g openclaw         # Установить OpenClaw
openclaw gateway install        # Настроить как сервис
openclaw channels add telegram  # Подключить Telegram-бота

cd /opt
git clone <repo> clawforge     # Клонировать ClawForge
cd clawforge
python setup.py                 # Установить: агенты + skill + реестр
```

```bash
# Управление:
python setup.py --update        # Обновить SOUL.md и skills
python setup.py --uninstall     # Удалить ClawForge, вернуть чистый OpenClaw
```

## 9. Scope MVP

### Включено

- 5 базовых агентов в OpenClaw
- Конвейер создания нового агента (analyst → developer → tester → validator)
- Расширение существующего агента (добавление skill / heartbeat)
- Переиспользование опыта из реестра при создании новых агентов
- Переключение между агентами
- Реестр агентов с поиском по capabilities
- Создание автоматизаций (heartbeat/cron)
- Удаление агентов (с подтверждением)
- Skill claw-forge (связка OpenClaw ↔ Python)
- Setup / update / uninstall скрипт

### Не включено

- Параллельное выполнение агентов (только последовательный конвейер)
- Web-дашборд
- Несколько пользователей (один Telegram-аккаунт)
- Версионирование агентов

## 10. Что даёт этот подход

- **Для демо:** "Напиши задачу в Telegram — система сама создаст агента и ты сможешь с ним работать"
- **Для собеседования:** Чистая архитектура, конвейер из специализированных агентов, self-expansion, единый формат агентов, минимум кода
- **Для масштабирования:** OpenClaw как runtime обеспечивает Telegram, память, LLM. Python-слой можно расширять: web-дашборд, мульти-юзер, параллелизм
