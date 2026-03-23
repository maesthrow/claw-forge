"""ClawForge deploy module — OpenClaw agent management via CLI."""

import os
import shlex
import shutil
import subprocess


OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_MAIN_WORKSPACE = os.environ.get("CLAWFORGE_MAIN_WORKSPACE", "/root/.openclaw/workspace")

OPENCLAW_DEFAULTS = ["BOOTSTRAP.md", "IDENTITY.md", "USER.md", "TOOLS.md", "HEARTBEAT.md"]


def run_cmd(cmd):
    """Run a shell command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nstderr: {result.stderr}")
    return result.stdout.strip()


def clean_openclaw_defaults(workspace_path, keep_agents_md=False):
    """Remove OpenClaw default template files from workspace."""
    to_remove = list(OPENCLAW_DEFAULTS)
    if not keep_agents_md:
        to_remove.append("AGENTS.md")
    for fname in to_remove:
        fpath = os.path.join(workspace_path, fname)
        if os.path.exists(fpath):
            os.remove(fpath)


def create_agent_workspace(name, soul_md, agents_md=None, skills=None):
    """Create workspace directory with SOUL.md and optional skills."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    os.makedirs(workspace, exist_ok=True)

    with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(soul_md)

    if agents_md:
        with open(os.path.join(workspace, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write(agents_md)

    if skills:
        skills_dir = os.path.join(workspace, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        for skill_name, skill_content in skills.items():
            skill_dir = os.path.join(skills_dir, skill_name)
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_content)

    return workspace


def register_agent(name, workspace_path):
    """Register agent in OpenClaw gateway."""
    result = run_cmd(f"openclaw agents add {shlex.quote(name)} --workspace {shlex.quote(workspace_path)} --non-interactive")

    # OpenClaw creates a default workspace-<name>/ dir with template files.
    # Remove all defaults and copy our files instead.
    openclaw_home = os.path.expanduser("~/.openclaw")
    default_workspace = os.path.join(openclaw_home, f"workspace-{name}")
    if os.path.exists(default_workspace):
        for fname in os.listdir(default_workspace):
            fpath = os.path.join(default_workspace, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)

        for fname in os.listdir(workspace_path):
            src = os.path.join(workspace_path, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(default_workspace, fname))

        our_skills = os.path.join(workspace_path, "skills")
        default_skills = os.path.join(default_workspace, "skills")
        if os.path.exists(our_skills):
            if os.path.exists(default_skills):
                shutil.rmtree(default_skills)
            shutil.copytree(our_skills, default_skills)

    # Clean OpenClaw defaults from our workspace
    clean_openclaw_defaults(workspace_path)

    return result


def delete_agent(name):
    """Delete agent from OpenClaw and remove all artifacts."""
    try:
        run_cmd(f"openclaw agents delete {shlex.quote(name)} --force")
    except RuntimeError:
        pass

    # Remove our workspace
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        shutil.rmtree(workspace)

    # Remove OpenClaw agent state (sessions, cache)
    openclaw_home = os.path.expanduser("~/.openclaw")
    agent_state = os.path.join(openclaw_home, "agents", name)
    if os.path.exists(agent_state):
        shutil.rmtree(agent_state)


def update_agent_soul(name, soul_md):
    """Update SOUL.md for an existing agent."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
            f.write(soul_md)

    # Also update workspace-<name> if it exists
    openclaw_home = os.path.expanduser("~/.openclaw")
    default_workspace = os.path.join(openclaw_home, f"workspace-{name}")
    if os.path.exists(default_workspace):
        with open(os.path.join(default_workspace, "SOUL.md"), "w", encoding="utf-8") as f:
            f.write(soul_md)


def add_skill_to_agent(agent_name, skill_name, skill_content):
    """Add a skill to an existing agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    skill_dir = os.path.join(workspace, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


def add_heartbeat(name, cron_expr, agent_name, message, telegram_user_id):
    """Create a cron job in OpenClaw."""
    return run_cmd(
        f"openclaw cron add --name {shlex.quote(name)} --cron {shlex.quote(cron_expr)} "
        f"--agent {shlex.quote(agent_name)} --message {shlex.quote(message)} "
        f"--deliver telegram:{shlex.quote(telegram_user_id)}"
    )


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
