# Reliable Agent Switching

**Date:** 2026-03-24
**Status:** Approved

## Problem

When a user switches agents via `/main` or `/set <name>` and then issues `/new` or `/reset`, the session may start with the **previous** agent instead of the one just selected.

### Root Cause

`switch_agent()` in `deploy.py` performs two sequential CLI commands:

1. `openclaw config set bindings '[]'` (~5 sec)
2. `openclaw agents bind --agent <name> --bind telegram:<id>` (~5 sec)

This creates a ~10 second window where the binding is either empty or still pointing to the old agent. `/new` and `/reset` are native OpenClaw commands processed by the gateway immediately — if fired during this window, they create a session for the wrong agent.

Additionally, `cmd_switch()` in `main.py` forks a child for greeting generation but the parent returns immediately, allowing the calling agent to respond before the binding is updated. The user sees a response and may press `/new` before the binding change completes.

### Evidence

Gateway logs show the gap:
```
17:09:02 — "Updated bindings" (clear)
17:09:12 — "Added bindings" (bind main)  ← 10 sec gap
```

## Solution

### 1. Atomic binding in `switch_agent()` (deploy.py)

Replace two CLI commands with one `openclaw config set bindings` that writes the full binding array atomically:

```python
def switch_agent(agent_name, telegram_user_id):
    openclaw_name = "main" if agent_name == "architect" else agent_name
    binding = json.dumps([{
        "type": "route",
        "agentId": openclaw_name,
        "match": {"channel": "telegram", "accountId": telegram_user_id}
    }])
    run_cmd(f"openclaw config set bindings {shlex.quote(binding)}")
    return openclaw_name
```

**Why this works:** `openclaw agents bind` only adds — it cannot replace. That's why clear+add was needed. `config set bindings` replaces the entire array in a single operation.

### 2. Sequential greeting after binding in `cmd_switch()` (main.py)

Move `switch_agent()` inside the forked child, before greeting generation. This ensures the greeting is only sent after the binding is confirmed:

```python
def cmd_switch(args):
    telegram_user_id = _get_telegram_user_id()
    openclaw_name = "main" if args.agent == "architect" else args.agent
    pid = os.fork()
    if pid > 0:
        return
    try:
        deploy.switch_agent(args.agent, telegram_user_id)
        greeting = deploy.call_agent(openclaw_name, "Представься...")
        deploy.send_notification("telegram", telegram_user_id, greeting)
    except Exception:
        pass
    finally:
        os._exit(0)
```

**Why this works:** The user cannot press `/new` before seeing the greeting, and the greeting only arrives after the binding is set.

### 3. Remove duplicated `architect → main` mapping

The mapping `"main" if agent_name == "architect" else agent_name` exists in both `deploy.py:switch_agent()` and `main.py:cmd_switch()`. Consolidate into `switch_agent()` which now returns the resolved `openclaw_name`.

## Files Changed

| File | Change |
|------|--------|
| `src/deploy.py` | `switch_agent()` — single atomic command, returns openclaw_name |
| `src/main.py` | `cmd_switch()` — greeting after switch, remove mapping duplication |

## Files NOT Changed

- `orchestration.py` — developer/tester prompts for generating SOUL.md with `/main` command stay as-is
- `skills/claw-forge/SKILL.md` — command definitions unchanged
- `setup.py` — unchanged

## Risk Assessment

- **Low risk:** uses official `openclaw config set` CLI, not raw file writes
- **Behavioral change:** greeting arrives slightly later (after binding vs before), but this is the correct order
- **No breaking changes** to agent creation, deletion, or other workflows
