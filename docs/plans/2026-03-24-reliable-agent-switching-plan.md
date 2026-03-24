# Reliable Agent Switching — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix race condition where `/new`/`/reset` after `/main`/`/set` starts a session with the wrong agent.

**Architecture:** Replace two-step binding (clear + add) with single atomic `openclaw config set bindings`. Move binding into forked child before greeting so user only sees response after binding is live. Remove duplicated `architect → main` mapping.

**Tech Stack:** Python, OpenClaw CLI

---

### Task 1: Atomic binding in `switch_agent()`

**Files:**
- Modify: `src/deploy.py:1-7` (add `import json`)
- Modify: `src/deploy.py:144-155` (rewrite `switch_agent`)

**Step 1: Add `json` import to deploy.py**

`deploy.py` currently imports `os`, `shlex`, `shutil`, `subprocess`. Add `json`:

```python
import json
import os
import shlex
import shutil
import subprocess
```

**Step 2: Rewrite `switch_agent()`**

Replace the current function (lines 144-155):

```python
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
```

With:

```python
def switch_agent(agent_name, telegram_user_id):
    """Switch Telegram routing to a different agent.

    Uses a single atomic config set instead of clear+bind (two commands)
    to eliminate the race window where /new or /reset could hit empty
    or stale bindings.

    Returns the resolved OpenClaw agent name (e.g. 'main' for 'architect').
    """
    openclaw_name = "main" if agent_name == "architect" else agent_name

    binding = json.dumps([{
        "type": "route",
        "agentId": openclaw_name,
        "match": {
            "channel": "telegram",
            "accountId": telegram_user_id
        }
    }])
    run_cmd(f"openclaw config set bindings {shlex.quote(binding)}")

    return openclaw_name
```

**Step 3: Verify on server**

```bash
ssh root@194.113.37.137
cd /opt/clawforge
# copy updated file
python3 -c "import src.deploy as d; print(d.switch_agent('architect', '541534272'))"
# Expected: prints "main", no errors
openclaw agents bindings
# Expected: main <- telegram accountId=541534272
```

**Step 4: Commit**

```bash
git add src/deploy.py
git commit -m "fix: atomic binding in switch_agent — single config set instead of clear+bind"
```

---

### Task 2: Sequential greeting + remove mapping duplication in `cmd_switch()`

**Files:**
- Modify: `src/main.py:84-104` (rewrite `cmd_switch`)

**Step 1: Rewrite `cmd_switch()`**

Replace the current function (lines 84-104):

```python
def cmd_switch(args):
    telegram_user_id = _get_telegram_user_id()
    deploy.switch_agent(args.agent, telegram_user_id)
    print(f"Переключено на агента: {args.agent}")

    # Send greeting in background (call_agent is slow, parent process may timeout)
    openclaw_name = "main" if args.agent == "architect" else args.agent
    pid = os.fork()
    if pid > 0:
        return  # parent returns immediately
    # child: generate and send greeting
    try:
        greeting = deploy.call_agent(
            openclaw_name,
            "Начинается новое взаимодействие. Представься пользователю как при первом сообщении в новой сессии."
        )
        deploy.send_notification("telegram", telegram_user_id, greeting)
    except Exception:
        pass
    finally:
        os._exit(0)
```

With:

```python
def cmd_switch(args):
    telegram_user_id = _get_telegram_user_id()

    # Fork immediately — parent returns to calling agent, child does
    # binding + greeting sequentially (binding MUST complete before greeting
    # so user cannot /new before the binding is live).
    pid = os.fork()
    if pid > 0:
        print(f"Переключение на агента: {args.agent}")
        return

    try:
        openclaw_name = deploy.switch_agent(args.agent, telegram_user_id)
        greeting = deploy.call_agent(
            openclaw_name,
            "Начинается новое взаимодействие. Представься пользователю как при первом сообщении в новой сессии."
        )
        deploy.send_notification("telegram", telegram_user_id, greeting)
    except Exception:
        pass
    finally:
        os._exit(0)
```

Key changes:
- `switch_agent()` moved inside fork — binding happens in child, not before fork
- Uses return value of `switch_agent()` instead of duplicating `architect → main` mapping
- `print()` message changed to "Переключение" (in progress) instead of "Переключено" (completed) since binding hasn't happened yet when parent returns

**Step 2: Verify on server**

```bash
ssh root@194.113.37.137
# copy updated file, then test:
# 1. In Telegram: /set thesis_maker → should switch and greet
# 2. In Telegram: /main → should switch back to architect and greet
# 3. In Telegram: /new → should start new session with architect (not thesis_maker)
# 4. Check gateway logs:
tail -20 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep -i bind
# Expected: single "Updated bindings" + "config change applied" per switch (no gap)
```

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "fix: greeting after binding — prevent race on /new after /main"
```

---

### Task 3: Deploy and end-to-end test

**Files:**
- Server: `/opt/clawforge/src/deploy.py`, `/opt/clawforge/src/main.py`

**Step 1: Deploy to server**

```bash
scp src/deploy.py src/main.py root@194.113.37.137:/opt/clawforge/src/
```

**Step 2: Clear pycache on server**

```bash
ssh root@194.113.37.137 "rm -rf /opt/clawforge/src/__pycache__"
```

**Step 3: End-to-end test sequence in Telegram**

1. Send any message → architect responds (confirm baseline)
2. `/set thesis_maker` → thesis_maker greets
3. `/main` → architect greets
4. `/new` immediately after greeting → **must be architect, not thesis_maker** (this was the bug)
5. `/set thesis_maker` → thesis_maker greets
6. `/reset` → **must be thesis_maker** (binding should persist for current agent)
7. `/main` → architect greets
8. `/reset` → **must be architect**

**Step 4: Verify in gateway logs**

```bash
ssh root@194.113.37.137 "tail -50 /tmp/openclaw/openclaw-\$(date +%Y-%m-%d).log | grep -E 'bind|config change'"
```

Expected per switch: one `"Updated bindings"` + one `"config change applied"` (no gap, no double entry).

**Step 5: Commit test results**

```bash
git commit --allow-empty -m "test: verified reliable agent switching on production server"
```
