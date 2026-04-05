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
