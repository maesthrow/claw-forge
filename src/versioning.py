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
