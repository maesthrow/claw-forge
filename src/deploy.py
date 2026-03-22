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
    return run_cmd(f'openclaw agents add {name} --workspace "{workspace_path}" --non-interactive')


def delete_agent(name):
    """Delete agent from OpenClaw and remove workspace."""
    try:
        run_cmd(f"openclaw agents delete {name} --yes")
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
    """Switch Telegram routing to a different agent."""
    # orchestrator is registered as "main" in OpenClaw
    openclaw_name = "main" if agent_name == "orchestrator" else agent_name

    if openclaw_name == "main":
        # Return to orchestrator: remove all custom bindings, main catches as default
        _unbind_all_telegram(telegram_user_id)
        return "Switched to main (default)"
    else:
        # Switch to specific agent: first unbind, then bind new
        _unbind_all_telegram(telegram_user_id)
        return run_cmd(
            f"openclaw agents bind --agent {openclaw_name} --bind telegram:{telegram_user_id}"
        )


def _unbind_all_telegram(telegram_user_id):
    """Remove all telegram bindings for a user so main (default) takes over."""
    # Get list of all non-default agents and try to unbind telegram from each
    result = subprocess.run(
        "openclaw agents list --json",
        shell=True, capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        try:
            import json
            data = json.loads(result.stdout)
            agents = data if isinstance(data, list) else data.get("agents", [])
            for agent in agents:
                agent_id = agent.get("id", "") if isinstance(agent, dict) else ""
                if agent_id and agent_id != "main":
                    # Try unbind, ignore errors (agent may not have this binding)
                    subprocess.run(
                        f"openclaw agents unbind --agent {agent_id} --bind telegram:{telegram_user_id}",
                        shell=True, capture_output=True, text=True, timeout=10
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass


def call_agent(agent_name, message):
    """Send a message to an agent and get the response."""
    escaped_message = message.replace('"', '\\"')
    return run_cmd(
        f'openclaw agent --agent {agent_name} --message "{escaped_message}" --timeout 300'
    )


def install_skill_to_orchestrator(skill_name, skill_content):
    """Install a skill into the orchestrator's workspace."""
    skill_dir = os.path.join(OPENCLAW_MAIN_WORKSPACE, "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_content)
