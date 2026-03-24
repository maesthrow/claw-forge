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

        # Copy our agent files to workspace
        src_dir = os.path.join(SCRIPT_DIR, "agents", agent)
        for fname in os.listdir(src_dir):
            src = os.path.join(src_dir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(workspace, fname))

        run_cmd(f'openclaw agents add {agent} --workspace "{workspace}" --non-interactive')

        # Sync our files to workspace-<name> (copy over defaults, don't delete)
        default_ws = os.path.join(OPENCLAW_HOME, f"workspace-{agent}")
        if os.path.exists(default_ws):
            for fname in os.listdir(workspace):
                src = os.path.join(workspace, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(default_ws, fname))
        print(f"  done")

    # 2. Architect SOUL.md + AGENTS.md + IDENTITY.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{total_steps}] Configuring architect...")

    src_dir = os.path.join(SCRIPT_DIR, "agents", "architect")
    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
        src = os.path.join(src_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(MAIN_WORKSPACE, fname))
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
    protect_file(os.path.join(MAIN_WORKSPACE, "IDENTITY.md"))
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
    unprotect_file(os.path.join(MAIN_WORKSPACE, "IDENTITY.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    # Update base agents
    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            src_dir = os.path.join(SCRIPT_DIR, "agents", agent)
            for fname in os.listdir(src_dir):
                src = os.path.join(src_dir, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(workspace, fname))
            # Sync to workspace-<name>
            default_ws = os.path.join(OPENCLAW_HOME, f"workspace-{agent}")
            if os.path.exists(default_ws):
                for fname in os.listdir(workspace):
                    src = os.path.join(workspace, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(default_ws, fname))
            print(f"  {agent} updated")

    # Update architect
    src_dir = os.path.join(SCRIPT_DIR, "agents", "architect")
    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
        src = os.path.join(src_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(MAIN_WORKSPACE, fname))
    print("  architect updated")

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
    protect_file(os.path.join(MAIN_WORKSPACE, "IDENTITY.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    print("\n=== Update complete ===")
    if telegram_id:
        print(f"Telegram ID: {telegram_id}")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    # Unprotect architect files before removal
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "IDENTITY.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    # 1. Remove created agents (from registry)
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
    import registry
    import deploy as deploy_mod
    registry.init_db()
    for agent in registry.list_agents():
        name = agent["name"]
        print(f"  Removing created agent {name}...")
        run_cmd(f"openclaw agents delete {name} --force")
        deploy_mod.unbind_agent_bot(name)
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
    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
        fpath = os.path.join(MAIN_WORKSPACE, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print(f"  architect {fname} removed")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)
        print("  skill claw-forge removed")

    # 4. Registry + config
    db_path = os.path.join(SCRIPT_DIR, "clawforge.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  registry removed")

    if os.path.exists(TELEGRAM_ID_FILE):
        os.remove(TELEGRAM_ID_FILE)
        print("  telegram ID config removed")

    # 5. Logs
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
