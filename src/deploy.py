"""ClawForge deploy module — OpenClaw agent management via CLI."""

import json
import os
import shlex
import shutil
import subprocess


OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_MAIN_WORKSPACE = os.environ.get("CLAWFORGE_MAIN_WORKSPACE", "/root/.openclaw/workspace")


def run_cmd(cmd):
    """Run a shell command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nstderr: {result.stderr}")
    return result.stdout.strip()


def get_telegram_user_id():
    """Get Telegram user ID from config file or environment."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".telegram_id")
    try:
        with open(config_path, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid
    except FileNotFoundError:
        pass
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")


def create_agent_workspace(name, soul_md, agents_md=None, identity_md=None, skills=None, data_files=None, scripts=None):
    """Create workspace directory with SOUL.md, AGENTS.md, IDENTITY.md, skills and data files."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    os.makedirs(workspace, exist_ok=True)

    with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(soul_md)

    if agents_md:
        with open(os.path.join(workspace, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write(agents_md)

    if identity_md:
        with open(os.path.join(workspace, "IDENTITY.md"), "w", encoding="utf-8") as f:
            f.write(identity_md)

    if skills:
        skills_dir = os.path.join(workspace, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        for skill_name, skill_content in skills.items():
            skill_dir = os.path.join(skills_dir, skill_name)
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_content)

    if data_files:
        for fname, content in data_files.items():
            with open(os.path.join(workspace, fname), "w", encoding="utf-8") as f:
                f.write(content)

    if scripts:
        scripts_dir = os.path.join(workspace, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        for filename, content in scripts.items():
            filepath = os.path.join(scripts_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(filepath, 0o755)

    return workspace


def register_agent(name, workspace_path):
    """Register agent in OpenClaw gateway."""
    # Save our files before openclaw agents add (it overwrites with defaults)
    our_files = {}
    for fname in os.listdir(workspace_path):
        fpath = os.path.join(workspace_path, fname)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                our_files[fname] = f.read()

    result = run_cmd(f"openclaw agents add {shlex.quote(name)} --workspace {shlex.quote(workspace_path)} --non-interactive")

    # Restore our files over OpenClaw defaults
    for fname, content in our_files.items():
        with open(os.path.join(workspace_path, fname), "w", encoding="utf-8") as f:
            f.write(content)

    # Sync to workspace-<name> (if OpenClaw created it)
    default_workspace = os.path.join(OPENCLAW_HOME, f"workspace-{name}")
    if os.path.exists(default_workspace):
        for fname, content in our_files.items():
            with open(os.path.join(default_workspace, fname), "w", encoding="utf-8") as f:
                f.write(content)

        our_skills = os.path.join(workspace_path, "skills")
        default_skills = os.path.join(default_workspace, "skills")
        if os.path.exists(our_skills):
            if os.path.exists(default_skills):
                shutil.rmtree(default_skills)
            shutil.copytree(our_skills, default_skills)

    return result


def delete_agent(name):
    """Delete agent from OpenClaw and remove all artifacts."""
    try:
        run_cmd(f"openclaw agents delete {shlex.quote(name)} --force")
    except RuntimeError:
        pass

    # Remove bot binding
    unbind_agent_bot(name)

    # Remove cron jobs for this agent and restart gateway to apply
    if _remove_agent_cron_jobs(name):
        try:
            run_cmd("openclaw gateway restart")
        except RuntimeError:
            pass

    # Remove our workspace
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    shutil.rmtree(workspace, ignore_errors=True)

    # Remove OpenClaw agent state (sessions, cache)
    agent_state = os.path.join(OPENCLAW_HOME, "agents", name)
    shutil.rmtree(agent_state, ignore_errors=True)


def _remove_agent_cron_jobs(agent_name):
    """Remove all cron jobs for an agent from jobs.json. Returns True if any were removed."""
    jobs_path = os.path.join(OPENCLAW_HOME, "cron", "jobs.json")
    try:
        with open(jobs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        original_count = len(data.get("jobs", []))
        data["jobs"] = [j for j in data.get("jobs", []) if j.get("agentId") != agent_name]
        if len(data["jobs"]) != original_count:
            with open(jobs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


def update_agent_files(name, soul_md=None, agents_md=None, identity_md=None, skills=None, data_files=None, scripts=None):
    """Update files for an existing agent. Only writes provided files."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    default_workspace = os.path.join(OPENCLAW_HOME, f"workspace-{name}")

    file_map = {}
    if soul_md:
        file_map["SOUL.md"] = soul_md
    if agents_md:
        file_map["AGENTS.md"] = agents_md
    if identity_md:
        file_map["IDENTITY.md"] = identity_md

    # Write files to both workspaces
    for ws in [workspace, default_workspace]:
        if not os.path.exists(ws):
            continue
        for fname, content in file_map.items():
            with open(os.path.join(ws, fname), "w", encoding="utf-8") as f:
                f.write(content)

    # Skills
    if skills:
        for skill_name, skill_content in skills.items():
            add_skill_to_agent(name, skill_name, skill_content)

    # Data files (only if they don't already exist — don't overwrite live data)
    if data_files:
        for ws in [workspace, default_workspace]:
            if not os.path.exists(ws):
                continue
            for fname, content in data_files.items():
                fpath = os.path.join(ws, fname)
                if not os.path.exists(fpath):
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(content)

    if scripts:
        install_scripts(name, scripts)


def add_skill_to_agent(agent_name, skill_name, skill_content):
    """Add a skill to an existing agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    skill_dir = os.path.join(workspace, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


def install_scripts(agent_name, scripts):
    """Install executable scripts to agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    scripts_dir = os.path.join(workspace, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for filename, content in scripts.items():
        filepath = os.path.join(scripts_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(filepath, 0o755)
    # Sync to default workspace
    default_workspace = os.path.join(OPENCLAW_HOME, f"workspace-{agent_name}")
    if os.path.exists(default_workspace):
        default_scripts = os.path.join(default_workspace, "scripts")
        if os.path.exists(default_scripts):
            shutil.rmtree(default_scripts)
        shutil.copytree(scripts_dir, default_scripts)


def install_system_deps(deps):
    """Install system dependencies needed by agent scripts."""
    for dep in deps:
        try:
            run_cmd(f"npm list -g {dep} 2>/dev/null || npm install -g {dep}")
        except RuntimeError:
            pass  # Best effort — tester will catch if it doesn't work


def add_heartbeat(name, cron_expr, agent_name, message, telegram_user_id, enabled=False):
    """Create a cron job by writing directly to OpenClaw's jobs.json.

    Uses native cron schedule format (kind: "cron") which OpenClaw
    supports natively. Bypasses `openclaw cron add` CLI which has a
    WebSocket auth bug in loopback mode.
    """
    import uuid
    import time

    cron_dir = os.path.join(OPENCLAW_HOME, "cron")
    os.makedirs(cron_dir, exist_ok=True)
    jobs_path = os.path.join(cron_dir, "jobs.json")

    # Load existing jobs
    try:
        with open(jobs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"version": 1, "jobs": []}

    # Remove existing job with same name (idempotent)
    data["jobs"] = [j for j in data["jobs"] if j.get("name") != name]

    now_ms = int(time.time() * 1000)

    data["jobs"].append({
        "id": str(uuid.uuid4()),
        "name": name,
        "enabled": enabled,
        "agentId": agent_name,
        "sessionTarget": "isolated",
        "wakeMode": "now",
        "schedule": {
            "kind": "cron",
            "expr": cron_expr,
            "tz": "UTC"
        },
        "payload": {
            "kind": "agentTurn",
            "message": message
        },
        "delivery": {
            "mode": "none"
        },
        "state": {},
        "createdAtMs": now_ms,
        "updatedAtMs": now_ms
    })

    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clear_pipeline_sessions():
    """Clear session history for all pipeline agents to prevent context buildup."""
    for agent in ["analyst", "developer", "reviewer", "tester"]:
        sessions_dir = os.path.join(OPENCLAW_HOME, "agents", agent, "sessions")
        if os.path.exists(sessions_dir):
            shutil.rmtree(sessions_dir, ignore_errors=True)
            os.makedirs(sessions_dir, exist_ok=True)


def call_agent(agent_name, message):
    """Send a message to an agent and get the response."""
    return run_cmd(
        f"openclaw agent --agent {shlex.quote(agent_name)} "
        f"--message {shlex.quote(message)} --timeout 600"
    )


def send_notification(channel, user_id, message):
    """Send a notification message to user via OpenClaw."""
    try:
        run_cmd(
            f"openclaw message send --channel {shlex.quote(channel)} "
            f"--target {shlex.quote(user_id)} -m {shlex.quote(message)}"
        )
    except RuntimeError as e:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "notification_errors.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"Failed to send to {channel}:{user_id} — {str(e)[:200]}\n")


def install_skill_to_architect(skill_name, skill_content):
    """Install a skill into the architect's workspace."""
    skill_dir = os.path.join(OPENCLAW_MAIN_WORKSPACE, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


def bind_agent_to_bot(agent_name, bot_token, telegram_user_id):
    """Bind a Telegram bot to an agent via multi-account config.

    Adds a new account to channels.telegram.accounts and a static
    binding in the bindings array. Gateway hot-reloads on config change.
    """
    config_path = os.path.join(OPENCLAW_HOME, "openclaw.json")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Add telegram account
    accounts = config.setdefault("channels", {}).setdefault("telegram", {}).setdefault("accounts", {})
    accounts[agent_name] = {
        "botToken": bot_token,
        "dmPolicy": "pairing"
    }

    # Add static binding
    bindings = config.setdefault("bindings", [])
    # Remove existing binding for this agent if any
    bindings = [b for b in bindings if b.get("agentId") != agent_name]
    bindings.append({
        "type": "route",
        "agentId": agent_name,
        "match": {
            "channel": "telegram",
            "accountId": agent_name
        }
    })
    config["bindings"] = bindings

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def unbind_agent_bot(agent_name):
    """Remove a Telegram bot binding for an agent.

    NEVER removes 'default' or 'main' — these are the architect's core config.
    """
    if agent_name in ("default", "main"):
        return  # Protect architect's bot token and binding

    config_path = os.path.join(OPENCLAW_HOME, "openclaw.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Remove telegram account
        accounts = config.get("channels", {}).get("telegram", {}).get("accounts", {})
        accounts.pop(agent_name, None)

        # Remove binding
        bindings = config.get("bindings", [])
        config["bindings"] = [b for b in bindings if b.get("agentId") != agent_name]

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        pass
