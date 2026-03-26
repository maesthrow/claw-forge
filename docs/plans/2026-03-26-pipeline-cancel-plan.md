# Pipeline Cancel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to cancel agent creation pipeline via text command to architect, with cleanup of partial artifacts.

**Architecture:** PID-file (`logs/pipeline.pid`) tracks running pipeline. New `cmd_cancel` kills process and cleans up. `cmd_create` writes PID-file in child, checks for running pipeline before fork. `run_pipeline` updates PID-file with agent_name after analyst. Architect SKILL.md gets cancel section.

**Tech Stack:** Python 3.10+, os/signal for process management, JSON PID-file

**Design doc:** `docs/plans/2026-03-26-pipeline-cancel-design.md`

---

### Task 1: PID-file helper functions in main.py

**Files:**
- Modify: `src/main.py`

**Step 1: Add imports**

Add `signal` to imports at top of `src/main.py`:

```python
import signal
```

**Step 2: Add PID-file helper functions after imports, before `cmd_create`**

```python
PIPELINE_PID_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "pipeline.pid")


def save_pipeline_pid(pid, agent_name=None):
    """Save pipeline PID to file."""
    os.makedirs(os.path.dirname(PIPELINE_PID_FILE), exist_ok=True)
    data = {
        "pid": pid,
        "started_at": datetime.datetime.now().isoformat()
    }
    if agent_name:
        data["agent_name"] = agent_name
    with open(PIPELINE_PID_FILE, "w") as f:
        json.dump(data, f)


def read_pipeline_pid():
    """Read pipeline PID file. Returns dict or None."""
    try:
        with open(PIPELINE_PID_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def remove_pipeline_pid():
    """Remove pipeline PID file."""
    try:
        os.remove(PIPELINE_PID_FILE)
    except FileNotFoundError:
        pass


def is_pipeline_running():
    """Check if a pipeline is currently running."""
    data = read_pipeline_pid()
    if not data:
        return False
    try:
        os.kill(data["pid"], 0)
        return True
    except (OSError, ProcessLookupError):
        # Process dead, clean up stale PID file
        remove_pipeline_pid()
        return False
```

Also add `import datetime` to imports if not present.

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/main.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Update cmd_create to use PID-file

**Files:**
- Modify: `src/main.py` — `cmd_create` function

**Step 1: Replace cmd_create with PID-file support**

```python
def cmd_create(args):
    if args.notify:
        channel, user_id = args.notify.split(":")

        # Check if pipeline already running
        if is_pipeline_running():
            print("Конвейер уже работает. Напиши «отмена» чтобы остановить.")
            return

        pid = os.fork()
        if pid > 0:
            # Parent: return immediately (architect sends confirmation via SKILL.md)
            return
        # Child: save PID and run pipeline
        save_pipeline_pid(os.getpid())
        try:
            result = orchestration.run_pipeline(args.task)
            msg = result.get("message", "Конвейер завершён.")
            if result.get("action") == "created":
                msg += f"\nЕсли есть токен Telegram-бота — пришли его чтобы привязать."
            elif result.get("action") == "extended":
                msg += f"\nАгент {result['agent_name']} расширен."
            elif result.get("action") == "reuse":
                msg += f"\nДля этой задачи подходит агент {result['agent_name']}."
            deploy.send_notification(channel, user_id, msg)
            # Restart gateway if heartbeat was created
            if result.get("action") == "created" and result.get("needs_heartbeat"):
                time.sleep(2)
                try:
                    deploy.run_cmd("openclaw gateway restart")
                except RuntimeError:
                    pass
        except Exception as e:
            deploy.send_notification(channel, user_id, f"Ошибка при создании агента: {str(e)[:300]}")
        finally:
            remove_pipeline_pid()
            os._exit(0)
    else:
        result = orchestration.run_pipeline(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/main.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 3: Update run_pipeline to write agent_name to PID-file

**Files:**
- Modify: `src/orchestration.py` — `run_pipeline` function

**Step 1: Add update_pipeline_pid function to orchestration.py**

After imports, add:

```python
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
```

**Step 2: Call it in run_pipeline after analyst returns agent_name**

After `requirements = call_agent_with_retry("analyst", analyst_prompt)` and `time.sleep(PIPELINE_STEP_DELAY)`, before `validate_agent_name`:

```python
    requirements = call_agent_with_retry("analyst", analyst_prompt)
    time.sleep(PIPELINE_STEP_DELAY)

    # Update PID file with agent name for cancel cleanup
    if requirements.get("agent_name"):
        update_pipeline_agent_name(requirements["agent_name"])

    # Validate agent name
```

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/orchestration.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 4: Add cmd_cancel command

**Files:**
- Modify: `src/main.py` — new function + argparse registration

**Step 1: Add cmd_cancel function (after cmd_create)**

```python
def cmd_cancel(args):
    data = read_pipeline_pid()
    if not data:
        print("Нет активного конвейера.")
        return

    pid = data["pid"]

    # Check if process is alive
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        remove_pipeline_pid()
        print("Конвейер уже завершился.")
        return

    # Kill the process
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass

    # Cleanup partial artifacts
    agent_name = data.get("agent_name")
    if agent_name:
        agent = registry.get_agent(agent_name)
        if agent:
            try:
                deploy.delete_agent(agent_name)
            except Exception:
                pass
            registry.remove_agent(agent_name)

    remove_pipeline_pid()

    if args.notify:
        channel, user_id = args.notify.split(":")
        deploy.send_notification(channel, user_id, "Создание агента отменено.")
    print("Конвейер остановлен.")
```

**Step 2: Register cancel command in argparse (in `main` function)**

After `p_delete` block, add:

```python
    p_cancel = subparsers.add_parser("cancel", help="Cancel running pipeline")
    p_cancel.add_argument("--notify", help="Notify target after cancellation")
    p_cancel.set_defaults(func=cmd_cancel)
```

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/main.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 5: Update architect SKILL.md on server

**Files:**
- Modify on server: `/root/.openclaw/workspace/skills/claw-forge/SKILL.md`

**Step 1: Add cancel section to SKILL.md**

After the "Создать агента" section, add:

```markdown
## Отмена создания агента

Когда пользователь просит отменить, остановить, прекратить создание агента:

```bash
python3 /opt/clawforge/src/main.py cancel --notify telegram:541534272
```

После вызова скажи пользователю результат команды.
```

**Step 2: Verify on server**

Run: `ssh root@194.113.37.137 "grep -c 'cancel' /root/.openclaw/workspace/skills/claw-forge/SKILL.md"`
Expected: at least 2 matches

---

### Task 6: Commit and deploy

**Step 1: Check diff**

Run: `git diff src/main.py src/orchestration.py`

Verify:
- PID-file helpers added to main.py
- cmd_create uses PID-file
- cmd_cancel added
- orchestration.py has update_pipeline_agent_name

**Step 2: Commit**

```bash
git add src/main.py src/orchestration.py
git commit -m "feat: add pipeline cancel command with PID tracking and cleanup"
```

**Step 3: Deploy**

```bash
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__"
```

**Step 4: Update SKILL.md on server (Task 5)**

**Step 5: Verify**

```bash
ssh root@194.113.37.137 "grep -n 'pipeline_pid\|cmd_cancel\|PIPELINE_PID' /opt/clawforge/src/main.py | head -10"
```

Expected: functions found in file.
