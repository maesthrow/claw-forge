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


def list_versions(agent_name):
    """Return manifest dict with current + versions list, sorted newest first."""
    manifest = _load_manifest(agent_name)
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
        sorted_versions = sorted(manifest["versions"], key=lambda v: v["created_at"])
        for i, v in enumerate(sorted_versions):
            if v["id"] == current_id and i > 0:
                return sorted_versions[i - 1]
        return None

    try:
        num = int(version_ref)
        for v in manifest["versions"]:
            if v["number"] == num:
                return v
    except (ValueError, TypeError):
        pass

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

    _copy_snapshot_to_workspace(snapshot_dir, workspace)

    target_cron = _load_cron_from_snapshot(snapshot_dir)
    cron_changed = _restore_cron(agent_name, target_cron)

    manifest["current"] = target["id"]
    _save_manifest(agent_name, manifest)

    return {
        "status": "ok",
        "version": target,
        "cron_changed": cron_changed
    }
