"""ClawForge deploy module — OpenClaw agent management via CLI."""

import os
import subprocess
import shutil


OPENCLAW_WORKSPACES = os.environ.get("CLAWFORGE_WORKSPACES", "/root/.openclaw/workspaces")
OPENCLAW_MAIN_WORKSPACE = os.environ.get("CLAWFORGE_MAIN_WORKSPACE", "/root/.openclaw/workspace")


def run_cmd(cmd):
    """Run a shell command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nstderr: {result.stderr}")
    return result.stdout.strip()


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
    result = run_cmd(f'openclaw agents add {name} --workspace "{workspace_path}" --non-interactive')

    # OpenClaw creates a default workspace-<name>/ dir with template files
    # (AGENTS.md, BOOTSTRAP.md, IDENTITY.md, etc.) that conflict with ours.
    # Remove all defaults and copy our files instead.
    openclaw_home = os.path.expanduser("~/.openclaw")
    default_workspace = os.path.join(openclaw_home, f"workspace-{name}")
    if os.path.exists(default_workspace):
        # Remove all default template files
        for fname in os.listdir(default_workspace):
            fpath = os.path.join(default_workspace, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)

        # Copy our files into the default workspace
        for fname in os.listdir(workspace_path):
            src = os.path.join(workspace_path, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(default_workspace, fname))

        # Copy skills directory if exists
        our_skills = os.path.join(workspace_path, "skills")
        default_skills = os.path.join(default_workspace, "skills")
        if os.path.exists(our_skills):
            if os.path.exists(default_skills):
                shutil.rmtree(default_skills)
            shutil.copytree(our_skills, default_skills)

    return result


def delete_agent(name):
    """Delete agent from OpenClaw and remove workspace."""
    try:
        run_cmd(f"openclaw agents delete {name} --force")
    except RuntimeError:
        pass

    workspace = os.path.join(OPENCLAW_WORKSPACES, name)
    if os.path.exists(workspace):
        shutil.rmtree(workspace)


def add_skill_to_agent(agent_name, skill_name, skill_content):
    """Add a skill to an existing agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    skill_dir = os.path.join(workspace, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)


def add_heartbeat(name, cron_expr, agent_name, message, telegram_user_id):
    """Create a cron job in OpenClaw."""
    escaped_message = message.replace('"', '\\"')
    return run_cmd(
        f'openclaw cron add --name "{name}" --cron "{cron_expr}" '
        f'--agent {agent_name} --message "{escaped_message}" '
        f'--deliver telegram:{telegram_user_id}'
    )


def switch_agent(agent_name, telegram_user_id):
    """Switch Telegram routing to a different agent via config set (atomic)."""
    # architect is registered as "main" in OpenClaw
    openclaw_name = "main" if agent_name == "architect" else agent_name

    if openclaw_name == "main":
        # Return to architect: clear all bindings, main catches as default
        return run_cmd("openclaw config set bindings '[]'")
    else:
        # Switch to specific agent: set binding directly
        binding = (
            f'[{{"type":"route","agentId":"{openclaw_name}",'
            f'"match":{{"channel":"telegram","accountId":"{telegram_user_id}"}}}}]'
        )
        return run_cmd(f"openclaw config set bindings '{binding}'")


def call_agent(agent_name, message):
    """Send a message to an agent and get the response."""
    escaped_message = message.replace('"', '\\"')
    return run_cmd(
        f'openclaw agent --agent {agent_name} --message "{escaped_message}" --timeout 600'
    )


def send_notification(channel, user_id, message):
    """Send a notification message to user via OpenClaw."""
    escaped = message.replace('"', '\\"').replace('\n', '\\n')
    try:
        run_cmd(f'openclaw message send --channel {channel} --target {user_id} -m "{escaped}"')
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
