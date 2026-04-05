# Versioning и rollback агентов — План реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Каждое изменение агента создаёт снапшот в `versions/` внутри workspace. Пользователь может посмотреть историю и откатиться на любую версию.

**Architecture:** Новый модуль `src/versioning.py` с функциями для создания/отката снапшотов и управления манифестом. Интеграция в `orchestration.py` (автоснапшоты после deploy) и `main.py` (CLI команды). Manifest-файл `versions/_manifest.json` хранит список версий и указатель current.

**Tech Stack:** Python 3, shutil (copy), json, pathlib. Без внешних зависимостей.

**Design doc:** `docs/plans/2026-04-05-agent-versioning-design.md`

---

### Task 1: Создать модуль versioning.py с константами и базовыми хелперами

**Files:**
- Create: `src/versioning.py`

**Step 1: Создать файл с константами и хелперами манифеста**

Содержимое `src/versioning.py`:

```python
"""Agent versioning — snapshot workspace files for rollback."""

import datetime
import json
import os
import shutil

OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")

OPENCLAW_DEFAULT_FILES = {"USER.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"}
BLACKLISTED_DIRS = {"node_modules", ".openclaw", ".git", "versions"}
BLACKLISTED_FILES = {"package-lock.json"}
MAX_VERSIONS = 8


def _workspace_path(agent_name):
    return os.path.join(OPENCLAW_WORKSPACES, agent_name)


def _versions_dir(agent_name):
    return os.path.join(_workspace_path(agent_name), "versions")


def _manifest_path(agent_name):
    return os.path.join(_versions_dir(agent_name), "_manifest.json")


def _load_manifest(agent_name):
    """Load manifest or return empty structure if not exists."""
    path = _manifest_path(agent_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"current": None, "versions": []}


def _save_manifest(agent_name, manifest):
    """Save manifest atomically."""
    versions_dir = _versions_dir(agent_name)
    os.makedirs(versions_dir, exist_ok=True)
    path = _manifest_path(agent_name)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _next_version_number(manifest):
    """Return next monotonic version number (never reuses)."""
    if not manifest["versions"]:
        return 1
    return max(v["number"] for v in manifest["versions"]) + 1
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 3: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add versioning module scaffolding"
```

---

### Task 2: Функции копирования workspace ↔ snapshot

**Files:**
- Modify: `src/versioning.py` — добавить функции копирования

**Step 1: Добавить `_copy_workspace_to_snapshot()`**

Добавить в `src/versioning.py` после `_next_version_number()`:

```python
def _should_skip(name, is_dir):
    """Check if file/dir should be excluded from snapshot (blacklist)."""
    if is_dir:
        return name in BLACKLISTED_DIRS
    return name in OPENCLAW_DEFAULT_FILES or name in BLACKLISTED_FILES


def _copy_workspace_to_snapshot(workspace, snapshot_dir):
    """Copy workspace files to snapshot dir, respecting blacklist."""
    os.makedirs(snapshot_dir, exist_ok=True)
    for entry in os.listdir(workspace):
        src = os.path.join(workspace, entry)
        if os.path.isdir(src):
            if _should_skip(entry, is_dir=True):
                continue
            shutil.copytree(src, os.path.join(snapshot_dir, entry))
        elif os.path.isfile(src):
            if _should_skip(entry, is_dir=False):
                continue
            shutil.copy2(src, os.path.join(snapshot_dir, entry))


def _copy_snapshot_to_workspace(snapshot_dir, workspace):
    """Restore snapshot files into workspace.

    First removes managed files from workspace (whitelist protects OpenClaw defaults),
    then copies snapshot contents on top.
    """
    # Remove managed files/dirs from workspace
    for entry in os.listdir(workspace):
        path = os.path.join(workspace, entry)
        if os.path.isdir(path):
            if _should_skip(entry, is_dir=True):
                continue
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            if _should_skip(entry, is_dir=False):
                continue
            try:
                os.remove(path)
            except OSError:
                pass

    # Copy snapshot contents
    for entry in os.listdir(snapshot_dir):
        src = os.path.join(snapshot_dir, entry)
        dst = os.path.join(workspace, entry)
        # Skip cron.json — handled separately
        if entry == "cron.json":
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 3: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add workspace <-> snapshot copy functions"
```

---

### Task 3: Функции для работы с cron в снапшотах

**Files:**
- Modify: `src/versioning.py`

**Step 1: Добавить функции сохранения и восстановления cron**

Добавить в `src/versioning.py` после `_copy_snapshot_to_workspace()`:

```python
def _save_cron_to_snapshot(agent_name, snapshot_dir):
    """Save agent's cron job data to snapshot dir, if exists."""
    jobs_path = os.path.join(OPENCLAW_HOME, "cron", "jobs.json")
    try:
        with open(jobs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    for job in data.get("jobs", []):
        if job.get("agentId") == agent_name:
            cron_snapshot_path = os.path.join(snapshot_dir, "cron.json")
            with open(cron_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(job, f, ensure_ascii=False, indent=2)
            return


def _load_cron_from_snapshot(snapshot_dir):
    """Load cron job data from snapshot dir, or None if no cron was saved."""
    cron_path = os.path.join(snapshot_dir, "cron.json")
    try:
        with open(cron_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _restore_cron(agent_name, target_cron):
    """Restore cron job state to match target_cron (may be None).

    Returns True if jobs.json was modified (caller should restart gateway).
    """
    jobs_path = os.path.join(OPENCLAW_HOME, "cron", "jobs.json")
    try:
        with open(jobs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"version": 1, "jobs": []}

    original_jobs = list(data.get("jobs", []))
    # Remove existing cron for this agent
    data["jobs"] = [j for j in original_jobs if j.get("agentId") != agent_name]

    had_cron = len(data["jobs"]) != len(original_jobs)

    if target_cron is not None:
        data["jobs"].append(target_cron)

    now_has_cron = target_cron is not None

    if had_cron == now_has_cron and target_cron is None:
        return False  # nothing changed

    os.makedirs(os.path.dirname(jobs_path), exist_ok=True)
    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return had_cron != now_has_cron or target_cron is not None
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 3: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add cron save/restore functions for snapshots"
```

---

### Task 4: Функция create_snapshot() с retention

**Files:**
- Modify: `src/versioning.py`

**Step 1: Добавить функцию enforce_retention()**

Добавить в `src/versioning.py`:

```python
def enforce_retention(agent_name, max_versions=MAX_VERSIONS):
    """Keep only MAX_VERSIONS newest snapshots, protect current.

    Returns list of removed version ids.
    """
    manifest = _load_manifest(agent_name)
    if len(manifest["versions"]) <= max_versions:
        return []

    current = manifest.get("current")
    # Sort by created_at ascending (oldest first)
    versions_by_age = sorted(manifest["versions"], key=lambda v: v["created_at"])

    to_remove = []
    for v in versions_by_age:
        if len(manifest["versions"]) - len(to_remove) <= max_versions:
            break
        if v["id"] == current:
            continue  # never remove current
        to_remove.append(v)

    versions_dir = _versions_dir(agent_name)
    for v in to_remove:
        snapshot_path = os.path.join(versions_dir, v["id"])
        shutil.rmtree(snapshot_path, ignore_errors=True)

    removed_ids = {v["id"] for v in to_remove}
    manifest["versions"] = [v for v in manifest["versions"] if v["id"] not in removed_ids]
    _save_manifest(agent_name, manifest)

    return list(removed_ids)
```

**Step 2: Добавить create_snapshot()**

Добавить в `src/versioning.py`:

```python
def create_snapshot(agent_name, source, comment, changed_files=None):
    """Create a snapshot of agent's current workspace state.

    Args:
        agent_name: name of the agent
        source: one of "created", "extend_existing", "quick_fix"
        comment: human-readable description of what changed
        changed_files: list of file paths that were modified (optional)

    Returns version dict, or None if workspace doesn't exist.
    """
    workspace = _workspace_path(agent_name)
    if not os.path.isdir(workspace):
        return None

    manifest = _load_manifest(agent_name)
    number = _next_version_number(manifest)
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    version_id = f"v{number}-{timestamp}"
    created_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    snapshot_dir = os.path.join(_versions_dir(agent_name), version_id)
    _copy_workspace_to_snapshot(workspace, snapshot_dir)
    _save_cron_to_snapshot(agent_name, snapshot_dir)

    version = {
        "id": version_id,
        "number": number,
        "created_at": created_at,
        "source": source,
        "comment": comment,
        "changed_files": changed_files or []
    }
    manifest["versions"].append(version)
    manifest["current"] = version_id
    _save_manifest(agent_name, manifest)

    enforce_retention(agent_name)

    return version
```

**Step 3: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 4: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add create_snapshot() with FIFO retention"
```

---

### Task 5: Функции list_versions() и get_version_info()

**Files:**
- Modify: `src/versioning.py`

**Step 1: Добавить функции**

Добавить в `src/versioning.py`:

```python
def list_versions(agent_name):
    """Return manifest dict with current + versions list, sorted newest first."""
    manifest = _load_manifest(agent_name)
    # Sort versions newest first by created_at
    manifest["versions"] = sorted(
        manifest["versions"],
        key=lambda v: v["created_at"],
        reverse=True
    )
    return manifest


def _resolve_version_ref(manifest, version_ref):
    """Resolve version reference to full version dict.

    version_ref can be:
    - int or numeric string: matches "number" field
    - full id string: "v2-2026-04-01T09-15-22"
    - "previous": previous version relative to current
    - "current": current version
    """
    if version_ref is None:
        return None

    if version_ref == "current":
        current_id = manifest.get("current")
        for v in manifest["versions"]:
            if v["id"] == current_id:
                return v
        return None

    if version_ref == "previous":
        current_id = manifest.get("current")
        # Sort by created_at ascending, find current, return one before
        sorted_versions = sorted(manifest["versions"], key=lambda v: v["created_at"])
        for i, v in enumerate(sorted_versions):
            if v["id"] == current_id and i > 0:
                return sorted_versions[i - 1]
        return None

    # Try as number
    try:
        num = int(version_ref)
        for v in manifest["versions"]:
            if v["number"] == num:
                return v
    except (ValueError, TypeError):
        pass

    # Try as full id
    for v in manifest["versions"]:
        if v["id"] == version_ref:
            return v

    return None


def get_version_info(agent_name, version_ref):
    """Get detailed info about a specific version.

    Returns dict with version metadata + file list, or None if not found.
    """
    manifest = _load_manifest(agent_name)
    version = _resolve_version_ref(manifest, version_ref)
    if not version:
        return None

    snapshot_dir = os.path.join(_versions_dir(agent_name), version["id"])
    files_info = []

    if os.path.isdir(snapshot_dir):
        for root, dirs, files in os.walk(snapshot_dir):
            for fname in files:
                if fname == "cron.json":
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, snapshot_dir)
                size = os.path.getsize(fpath)
                files_info.append({"path": rel, "size": size})

    cron_data = _load_cron_from_snapshot(snapshot_dir)

    return {
        "version": version,
        "files": sorted(files_info, key=lambda f: f["path"]),
        "cron": cron_data,
        "is_current": version["id"] == manifest.get("current")
    }
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 3: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add list_versions() and get_version_info()"
```

---

### Task 6: Функция rollback_to_version()

**Files:**
- Modify: `src/versioning.py`

**Step 1: Добавить rollback_to_version()**

Добавить в `src/versioning.py`:

```python
def rollback_to_version(agent_name, version_ref):
    """Restore agent workspace to target version.

    Returns dict:
    - {"status": "ok", "version": {...}, "cron_changed": bool}
    - {"status": "error", "reason": "..."}
    """
    workspace = _workspace_path(agent_name)
    if not os.path.isdir(workspace):
        return {"status": "error", "reason": "Агент не найден в реестре."}

    manifest = _load_manifest(agent_name)
    if not manifest["versions"]:
        return {"status": "error", "reason": "История пуста, откат невозможен."}

    target = _resolve_version_ref(manifest, version_ref)
    if not target:
        return {"status": "error", "reason": f"Версия {version_ref} не найдена."}

    if target["id"] == manifest.get("current"):
        return {"status": "error", "reason": "Это уже текущая версия, откат не нужен."}

    snapshot_dir = os.path.join(_versions_dir(agent_name), target["id"])
    if not os.path.isdir(snapshot_dir):
        return {"status": "error", "reason": f"Снапшот {target['id']} повреждён или удалён. Откат невозможен."}

    # Restore files
    _copy_snapshot_to_workspace(snapshot_dir, workspace)

    # Restore cron
    target_cron = _load_cron_from_snapshot(snapshot_dir)
    cron_changed = _restore_cron(agent_name, target_cron)

    # Update manifest
    manifest["current"] = target["id"]
    _save_manifest(agent_name, manifest)

    return {
        "status": "ok",
        "version": target,
        "cron_changed": cron_changed
    }
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 3: Коммит**

```bash
cd d:/dev/ClawForge
git add src/versioning.py
git commit -m "feat: add rollback_to_version() with cron restore"
```

---

### Task 7: Интеграция create_snapshot в orchestration.py

**Files:**
- Modify: `src/orchestration.py` — добавить снапшоты после deploy

**Step 1: Добавить импорт versioning**

В `src/orchestration.py` после `import registry` добавить:

```python
import versioning
```

**Step 2: Создать снапшот после deploy_new_agent()**

Найти в `deploy_new_agent()` строку `return {` с `"action": "created"` и ПЕРЕД этим return добавить:

```python
    # Create snapshot after successful deploy
    try:
        versioning.create_snapshot(agent_name, "created", "Создан с нуля")
    except Exception as e:
        print(f"Warning: snapshot creation failed for {agent_name}: {e}")
```

**Step 3: Создать снапшот после deploy_extension()**

Найти в `deploy_extension()` строку `return {` с `"action": "extended"` и ПЕРЕД этим return добавить:

```python
    # Create snapshot after successful extend
    try:
        description = requirements.get("description", "Обновление агента")
        versioning.create_snapshot(target_agent, "extend_existing", description)
    except Exception as e:
        print(f"Warning: snapshot creation failed for {target_agent}: {e}")
```

**Step 4: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 5: Коммит**

```bash
cd d:/dev/ClawForge
git add src/orchestration.py
git commit -m "feat: auto-snapshot after create_new and extend_existing"
```

---

### Task 8: CLI команды snapshot, history, rollback в main.py

**Files:**
- Modify: `src/main.py`

**Step 1: Добавить импорт versioning**

В `src/main.py` после `import deploy` добавить:

```python
import versioning
```

**Step 2: Добавить cmd_snapshot()**

В `src/main.py` после `cmd_delete()` добавить:

```python
def cmd_snapshot(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    version = versioning.create_snapshot(args.agent, "quick_fix", args.comment)
    if version is None:
        print(f"Не удалось создать снапшот: workspace агента '{args.agent}' не найден.")
        sys.exit(1)

    print(f"Снапшот создан: v{version['number']} ({version['id']})")
    print(f"Комментарий: {version['comment']}")
```

**Step 3: Добавить cmd_history()**

После `cmd_snapshot()` добавить:

```python
def _format_source(source):
    labels = {
        "created": "создан",
        "extend_existing": "extend",
        "quick_fix": "quick fix"
    }
    return labels.get(source, source)


def _format_date(iso_timestamp):
    """Format ISO timestamp to readable dd.MM.yyyy HH:MM."""
    try:
        dt = datetime.datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso_timestamp


def cmd_history(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    if args.version:
        info = versioning.get_version_info(args.agent, args.version)
        if not info:
            print(f"Версия {args.version} не найдена.")
            sys.exit(1)
        v = info["version"]
        print(f"{args.agent} v{v['number']} ({_format_source(v['source'])}) — {_format_date(v['created_at'])}")
        if info["is_current"]:
            print("  (текущая)")
        print()
        print(f"Комментарий: {v['comment']}")
        print(f"Создан: {v['source']}")
        if v.get("changed_files"):
            print(f"Изменено: {', '.join(v['changed_files'])}")
        print()
        cron = info["cron"]
        if cron:
            schedule = cron.get("schedule", {})
            print(f"Cron: {schedule.get('expr', '?')} {schedule.get('tz', '')}, enabled={cron.get('enabled', False)}")
        else:
            print("Cron: нет")
        print()
        print("Файлы:")
        for f in info["files"]:
            size_kb = f["size"] / 1024
            print(f"  {f['path']} ({size_kb:.1f} KB)")
        return

    manifest = versioning.list_versions(args.agent)
    if not manifest["versions"]:
        print(f"История {args.agent} пуста.")
        return

    current_id = manifest.get("current")
    current_num = None
    for v in manifest["versions"]:
        if v["id"] == current_id:
            current_num = v["number"]
            break

    print(f"История {args.agent} (текущая: v{current_num}):" if current_num else f"История {args.agent}:")
    print()
    for v in manifest["versions"]:
        marker = "  ← текущая" if v["id"] == current_id else ""
        print(f"v{v['number']} ({_format_source(v['source'])}) — {_format_date(v['created_at'])}{marker}")
        print(f"  Комментарий: {v['comment']}")
        if v.get("changed_files"):
            print(f"  Изменено: {', '.join(v['changed_files'])}")
        print()
    print(f"Откатить: python3 main.py rollback --agent {args.agent} --version <номер>")
```

**Step 4: Добавить cmd_rollback()**

После `cmd_history()` добавить:

```python
def cmd_rollback(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    result = versioning.rollback_to_version(args.agent, args.version)
    if result["status"] == "error":
        print(result["reason"])
        sys.exit(1)

    target = result["version"]
    print(f"Готово. Текущая версия {args.agent} — v{target['number']}.")

    # Gateway restart if cron changed
    if result["cron_changed"]:
        try:
            deploy.run_cmd("openclaw gateway restart")
        except RuntimeError as e:
            print(f"Warning: gateway restart failed: {e}")

    if args.notify:
        channel, user_id = args.notify.split(":")
        deploy.send_notification(
            channel, user_id,
            f"Агент '{args.agent}' откачен на v{target['number']}."
        )
```

**Step 5: Добавить subparsers в main()**

В `main()` после `p_cancel.set_defaults(func=cmd_cancel)` добавить:

```python
    p_snapshot = subparsers.add_parser("snapshot", help="Create a manual snapshot of agent")
    p_snapshot.add_argument("--agent", required=True, help="Agent name")
    p_snapshot.add_argument("--comment", required=True, help="Description of changes")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_history = subparsers.add_parser("history", help="Show agent version history")
    p_history.add_argument("--agent", required=True, help="Agent name")
    p_history.add_argument("--version", help="Show details for specific version (number or id or 'previous')")
    p_history.set_defaults(func=cmd_history)

    p_rollback = subparsers.add_parser("rollback", help="Rollback agent to previous version")
    p_rollback.add_argument("--agent", required=True, help="Agent name")
    p_rollback.add_argument("--version", required=True, help="Target version (number, id, or 'previous')")
    p_rollback.add_argument("--notify", help="Notify target after completion")
    p_rollback.set_defaults(func=cmd_rollback)
```

**Step 6: Убедиться что `import datetime` есть в main.py**

Проверить наличие `import datetime` в импортах `main.py`. Если отсутствует — добавить.

**Step 7: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/main.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

**Step 8: Коммит**

```bash
cd d:/dev/ClawForge
git add src/main.py
git commit -m "feat: add snapshot, history, rollback CLI commands"
```

---

### Task 9: Обновить skill claw-forge с командами history/rollback/snapshot

**Files:**
- Modify: `skills/claw-forge/SKILL.md`

**Step 1: Добавить новые секции**

В `skills/claw-forge/SKILL.md` после секции "## Поиск агента" добавить:

```markdown
## История версий агента

Когда пользователь спрашивает "покажи версии <имя>", "какие версии у <имя>", "история <имя>":

```bash
python3 /opt/clawforge/src/main.py history --agent <agent_name>
```

Для подробной информации о конкретной версии:

```bash
python3 /opt/clawforge/src/main.py history --agent <agent_name> --version <номер>
```

## Откат на предыдущую версию

Когда пользователь просит "откати <имя> на v<номер>", "верни <имя> как было", "откати <имя>":

ПЕРЕД вызовом откатa ОБЯЗАТЕЛЬНО:
1. Показать историю агента (history) и версию-цель (history --version)
2. Показать пользователю что изменится при откате (diff: файлы, cron)
3. Запросить явное подтверждение ("да", "откатываю")

```bash
python3 /opt/clawforge/src/main.py rollback --agent <agent_name> --version <номер> --notify telegram:{{TELEGRAM_USER_ID}}
```

После отката бот пришлёт пользователю уведомление.

## Сохранить снапшот (после быстрого фикса)

Когда завершил ручную правку файлов агента и успешно протестировал — ОБЯЗАТЕЛЬНО сохрани снапшот:

```bash
python3 /opt/clawforge/src/main.py snapshot --agent <agent_name> --comment "<краткое описание правки>"
```

Без этого шага правка не зафиксируется в истории, откат на эту версию позже будет невозможен.
```

**Step 2: Коммит**

```bash
cd d:/dev/ClawForge
git add skills/claw-forge/SKILL.md
git commit -m "feat: skill claw-forge — add history/rollback/snapshot commands"
```

---

### Task 10: Обновить Architect SOUL.md и AGENTS.md

**Files:**
- Modify: `agents/architect/SOUL.md`
- Modify: `agents/architect/AGENTS.md`

**Step 1: Обновить секцию "Быстрый фикс" в SOUL.md**

В `agents/architect/SOUL.md` найти блок:

```markdown
**Быстрый фикс (самостоятельно)**
Когда: точечная правка текста, формата, стиля, исправление конкретного бага.
1. Внеси точечные изменения в нужные файлы (не переписывай весь файл)
2. Запиши обновлённые файлы
3. ОБЯЗАТЕЛЬНО проверь результат:
   - Сбрось сессию агента: `/new` или через sessions tool — чтобы агент подхватил изменённые файлы
   - Запусти агента как субагента с тестовым сообщением, дождись ответа и сам оцени результат
   - Если результат не тот — исправь и проверь снова (до 2 раз)
   ВАЖНО: для запуска субагентов используй нативный tool запуска субагентов. НЕ используй exec с CLI-командами — они не дожидаются результата.
```

Заменить на:

```markdown
**Быстрый фикс (самостоятельно)**
Когда: точечная правка текста, формата, стиля, исправление конкретного бага.
1. Внеси точечные изменения в нужные файлы (не переписывай весь файл)
2. Запиши обновлённые файлы
3. ОБЯЗАТЕЛЬНО проверь результат:
   - Сбрось сессию агента: `/new` или через sessions tool — чтобы агент подхватил изменённые файлы
   - Запусти агента как субагента с тестовым сообщением, дождись ответа и сам оцени результат
   - Если результат не тот — исправь и проверь снова (до 2 раз)
   ВАЖНО: для запуска субагентов используй нативный tool запуска субагентов. НЕ используй exec с CLI-командами — они не дожидаются результата.
4. ОБЯЗАТЕЛЬНО после успешной проверки — сохрани снапшот: вызови skill claw-forge (команда snapshot) с кратким описанием правки. Без этого шага версия не зафиксируется в истории, откат потом будет невозможен. Если серия правок провалилась (тест так и не прошёл) — снапшот НЕ создавай.
```

**Step 2: Обновить секцию "Быстрый фикс" в AGENTS.md**

В `agents/architect/AGENTS.md` найти:

```markdown
## Быстрый фикс
- Перед правкой — загрузи и прочитай все файлы агента (SOUL.md, AGENTS.md, IDENTITY.md, skills, scripts)
- После ЛЮБОЙ прямой правки файлов агента — вызови тестера для проверки
- Не пропускай тестирование даже для «мелких» правок
- Если тестер нашёл проблему — исправь и протестируй снова (до 2 раз)
- Если правка затрагивает cron (jobs.json) — СНАЧАЛА напиши ответ пользователю, ПОТОМ запусти отложенный restart: exec `nohup sh -c 'sleep 5 && openclaw gateway restart' >/dev/null 2>&1 &`. НИКОГДА не вызывай openclaw gateway restart напрямую — это убьёт текущую сессию
```

Заменить на:

```markdown
## Быстрый фикс
- Перед правкой — загрузи и прочитай все файлы агента (SOUL.md, AGENTS.md, IDENTITY.md, skills, scripts)
- После ЛЮБОЙ прямой правки файлов агента — вызови тестера для проверки
- Не пропускай тестирование даже для «мелких» правок
- Если тестер нашёл проблему — исправь и протестируй снова (до 2 раз)
- ОБЯЗАТЕЛЬНО после успешного теста — создай снапшот через skill claw-forge (snapshot). БЕЗ ЭТОГО ПРАВКИ ПОТЕРЯЮТСЯ ПРИ ОТКАТЕ.
- Если правка затрагивает cron (jobs.json) — СНАЧАЛА напиши ответ пользователю, ПОТОМ запусти отложенный restart: exec `nohup sh -c 'sleep 5 && openclaw gateway restart' >/dev/null 2>&1 &`. НИКОГДА не вызывай openclaw gateway restart напрямую — это убьёт текущую сессию
```

**Step 3: Добавить правила про rollback в SOUL.md**

В `agents/architect/SOUL.md` найти секцию "## Когда вызывать skill claw-forge" и в список добавить:

```markdown
- Пользователь спрашивает про историю версий агента или просит откатить
```

**Step 4: Коммит**

```bash
cd d:/dev/ClawForge
git add agents/architect/SOUL.md agents/architect/AGENTS.md
git commit -m "feat: architect — snapshot after quick fix, rollback handling"
```

---

### Task 11: Финальная проверка и деплой

**Files:** none

**Step 1: Проверить синтаксис всех изменённых Python файлов**

Run:
```bash
python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/versioning.py', encoding='utf-8').read()); print('versioning.py ok')"
python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py', encoding='utf-8').read()); print('orchestration.py ok')"
python -c "import ast; ast.parse(open('d:/dev/ClawForge/src/main.py', encoding='utf-8').read()); print('main.py ok')"
```
Expected: `versioning.py ok`, `orchestration.py ok`, `main.py ok`

**Step 2: Проверить коммиты**

Run: `cd d:/dev/ClawForge && git log --oneline -12`
Expected: 10 новых коммитов сверху (tasks 1-10).

**Step 3: Push и деплой**

```bash
cd d:/dev/ClawForge
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__ && python3 setup.py --update"
```

Expected: `=== Update complete ===`

**Step 4: Smoke-тест на сервере**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && python3 -c \"import sys; sys.path.insert(0, 'src'); import versioning; print('import ok'); print('MAX_VERSIONS=' + str(versioning.MAX_VERSIONS))\""
```
Expected: `import ok`, `MAX_VERSIONS=8`

**Step 5: Проверить команду help**

```bash
ssh root@194.113.37.137 "python3 /opt/clawforge/src/main.py history --help 2>&1 | head -5"
```
Expected: Usage info про `history` subcommand.
