#!/usr/bin/env python3
"""ClawForge setup script — installs/updates/uninstalls on an OpenClaw server."""

import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
MAIN_WORKSPACE = os.path.join(OPENCLAW_HOME, "workspace")
WORKSPACES_DIR = os.path.join(OPENCLAW_HOME, "workspaces")
TELEGRAM_ID_FILE = os.path.join(SCRIPT_DIR, ".telegram_id")

BASE_AGENTS = ["analyst", "developer", "tester", "validator"]

OPENCLAW_DEFAULTS = ["BOOTSTRAP.md", "IDENTITY.md", "USER.md", "TOOLS.md", "HEARTBEAT.md"]


def run_cmd(cmd):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        print(f"  WARN: {result.stderr.strip()}")
    return result.returncode == 0


def protect_file(path):
    """Make file read-only (chmod 444)."""
    if os.path.exists(path):
        os.chmod(path, 0o444)


def unprotect_file(path):
    """Restore file to writable (chmod 644)."""
    if os.path.exists(path):
        os.chmod(path, 0o644)


def clean_workspace_defaults(workspace_path, keep_agents_md=False):
    """Remove OpenClaw default template files from workspace."""
    to_remove = list(OPENCLAW_DEFAULTS)
    if not keep_agents_md:
        to_remove.append("AGENTS.md")
    for fname in to_remove:
        fpath = os.path.join(workspace_path, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print(f"    removed {fname}")


def detect_telegram_id():
    """Auto-detect Telegram user ID from OpenClaw pairing data."""
    allow_path = os.path.join(OPENCLAW_HOME, "credentials", "telegram-default-allowFrom.json")
    if os.path.exists(allow_path):
        try:
            with open(allow_path) as f:
                data = json.load(f)
            ids = data.get("allowFrom", [])
            if ids:
                return ids[0]
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def get_telegram_id():
    """Get Telegram ID: saved file -> auto-detect -> None."""
    if os.path.exists(TELEGRAM_ID_FILE):
        with open(TELEGRAM_ID_FILE, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid

    tid = detect_telegram_id()
    if tid:
        save_telegram_id(tid)
    return tid


def save_telegram_id(tid):
    """Save Telegram ID to config file."""
    with open(TELEGRAM_ID_FILE, "w") as f:
        f.write(tid)
    print(f"  Telegram ID saved: {tid}")


def install_skill(src_path, dst_path, telegram_id):
    """Install SKILL.md with Telegram ID substitution."""
    with open(src_path, "r", encoding="utf-8") as f:
        content = f.read()
    if telegram_id:
        content = content.replace("{{TELEGRAM_USER_ID}}", telegram_id)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(content)


def install():
    print("=== ClawForge Setup ===\n")

    # Detect Telegram ID
    telegram_id = get_telegram_id()
    if not telegram_id:
        print("  WARNING: Telegram not paired yet. Run 'openclaw pairing approve telegram <CODE>' first.")
        print("  After pairing, run: python setup.py --update\n")

    total_steps = len(BASE_AGENTS) + 4

    # 1. Base agents
    for i, agent in enumerate(BASE_AGENTS, 1):
        print(f"[{i}/{total_steps}] Creating agent {agent}...")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        os.makedirs(workspace, exist_ok=True)

        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        shutil.copy2(src_soul, dst_soul)

        run_cmd(f'openclaw agents add {agent} --workspace "{workspace}" --non-interactive')

        # Clean OpenClaw defaults from workspace
        clean_workspace_defaults(workspace, keep_agents_md=False)

        # Clean workspace-<name> if exists
        default_ws = os.path.join(OPENCLAW_HOME, f"workspace-{agent}")
        if os.path.exists(default_ws):
            for fname in os.listdir(default_ws):
                fpath = os.path.join(default_ws, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            shutil.copy2(src_soul, os.path.join(default_ws, "SOUL.md"))
        print(f"  done")

    # 2. Architect SOUL.md + AGENTS.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{total_steps}] Configuring architect...")

    clean_workspace_defaults(MAIN_WORKSPACE, keep_agents_md=True)

    src_soul = os.path.join(SCRIPT_DIR, "agents", "architect", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)

    src_agents = os.path.join(SCRIPT_DIR, "agents", "architect", "AGENTS.md")
    dst_agents = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
    print("  done")

    # 3. claw-forge skill
    step += 1
    print(f"[{step}/{total_steps}] Installing skill claw-forge...")
    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    install_skill(src_skill, dst_skill, telegram_id)
    print("  done")

    # 4. Init registry
    step += 1
    print(f"[{step}/{total_steps}] Initializing registry...")
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
    import registry
    registry.init_db()
    print("  done")

    # 5. Protect architect config files (read-only)
    step += 1
    print(f"[{step}/{total_steps}] Protecting architect config files...")
    protect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))
    print("  done")

    print(f"\n=== ClawForge installed! ===")
    print(f"Base agents: {len(BASE_AGENTS) + 1} (architect + {', '.join(BASE_AGENTS)})")
    if telegram_id:
        print(f"Telegram ID: {telegram_id}")
    print(f"Send your bot a message in Telegram to start.")


def update():
    print("=== ClawForge Update ===\n")

    # Detect/update Telegram ID
    telegram_id = get_telegram_id()
    if not telegram_id:
        telegram_id = detect_telegram_id()
        if telegram_id:
            save_telegram_id(telegram_id)
        else:
            print("  WARNING: Telegram ID not found. SKILL.md will have unresolved placeholder.")

    # Unprotect before updating
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    # Update base agents
    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        if os.path.exists(workspace):
            shutil.copy2(src_soul, dst_soul)
            clean_workspace_defaults(workspace, keep_agents_md=False)
            print(f"  {agent} updated")

    # Update architect
    src_soul = os.path.join(SCRIPT_DIR, "agents", "architect", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  architect SOUL.md updated")

    src_agents = os.path.join(SCRIPT_DIR, "agents", "architect", "AGENTS.md")
    dst_agents = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
    print("  architect AGENTS.md updated")

    # Clean defaults from main workspace
    clean_workspace_defaults(MAIN_WORKSPACE, keep_agents_md=True)

    # Update skill with Telegram ID
    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    install_skill(src_skill, dst_skill, telegram_id)
    print("  skill claw-forge updated")

    # Re-protect after updating
    protect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    print("\n=== Update complete ===")
    if telegram_id:
        print(f"Telegram ID: {telegram_id}")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    # Unprotect architect files before removal
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    # 1. Remove created agents (from registry)
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
    import registry
    registry.init_db()
    for agent in registry.list_agents():
        name = agent["name"]
        print(f"  Removing created agent {name}...")
        run_cmd(f"openclaw agents delete {name} --force")
        wp = agent.get("workspace_path")
        if wp and os.path.exists(wp):
            shutil.rmtree(wp)
        agent_state = os.path.join(OPENCLAW_HOME, "agents", name)
        if os.path.exists(agent_state):
            shutil.rmtree(agent_state)
        print(f"  done")

    # 2. Remove base agents + their state dirs
    for agent in BASE_AGENTS:
        print(f"  Removing agent {agent}...")
        run_cmd(f"openclaw agents delete {agent} --force")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        agent_state = os.path.join(OPENCLAW_HOME, "agents", agent)
        if os.path.exists(agent_state):
            shutil.rmtree(agent_state)
        print(f"  done")

    # 3. Clean architect files from main workspace
    for fname in ["SOUL.md", "AGENTS.md"]:
        fpath = os.path.join(MAIN_WORKSPACE, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print(f"  architect {fname} removed")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)
        print("  skill claw-forge removed")

    # 4. Clear bindings
    run_cmd("openclaw config set bindings '[]'")
    print("  bindings cleared")

    # 5. Registry + config
    db_path = os.path.join(SCRIPT_DIR, "clawforge.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  registry removed")

    if os.path.exists(TELEGRAM_ID_FILE):
        os.remove(TELEGRAM_ID_FILE)
        print("  telegram ID config removed")

    # 6. Logs
    log_dir = os.path.join(SCRIPT_DIR, "logs")
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
        print("  logs removed")

    print("\n=== ClawForge uninstalled. OpenClaw is clean. ===")


def main():
    parser = argparse.ArgumentParser(description="ClawForge setup")
    parser.add_argument("--update", action="store_true", help="Update SOUL.md and skills")
    parser.add_argument("--uninstall", action="store_true", help="Remove ClawForge from OpenClaw")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    elif args.update:
        update()
    else:
        install()


if __name__ == "__main__":
    main()
