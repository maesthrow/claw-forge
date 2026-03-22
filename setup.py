#!/usr/bin/env python3
"""ClawForge setup script — installs/updates/uninstalls on an OpenClaw server."""

import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
MAIN_WORKSPACE = os.path.join(OPENCLAW_HOME, "workspace")
WORKSPACES_DIR = os.path.join(OPENCLAW_HOME, "workspaces")

BASE_AGENTS = ["analyst", "developer", "tester", "validator"]

# Files to protect with read-only permissions
PROTECTED_FILES = []  # populated during install


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
        PROTECTED_FILES.append(path)


def unprotect_file(path):
    """Restore file to writable (chmod 644)."""
    if os.path.exists(path):
        os.chmod(path, 0o644)


def install():
    print("=== ClawForge Setup ===\n")

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
        print(f"  done")

    # 2. Orchestrator SOUL.md + AGENTS.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{total_steps}] Configuring architect...")
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
    shutil.copy2(src_skill, dst_skill)
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
    print(f"Send your bot a message in Telegram to start.")


def update():
    print("=== ClawForge Update ===\n")

    # Unprotect before updating
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        if os.path.exists(workspace):
            shutil.copy2(src_soul, dst_soul)
            print(f"  {agent} SOUL.md updated")

    src_soul = os.path.join(SCRIPT_DIR, "agents", "architect", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  architect SOUL.md updated")

    src_agents = os.path.join(SCRIPT_DIR, "agents", "architect", "AGENTS.md")
    dst_agents = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
    print("  architect AGENTS.md updated")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(src_skill, dst_skill)
    print("  skill claw-forge updated")

    # Re-protect after updating
    protect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    protect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    print("\n=== Update complete ===")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    # Unprotect architect files before removal
    unprotect_file(os.path.join(MAIN_WORKSPACE, "SOUL.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "AGENTS.md"))
    unprotect_file(os.path.join(MAIN_WORKSPACE, "skills", "claw-forge", "SKILL.md"))

    for agent in BASE_AGENTS:
        print(f"  Removing agent {agent}...")
        run_cmd(f"openclaw agents delete {agent} --yes")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        print(f"  done")

    agents_md = os.path.join(MAIN_WORKSPACE, "AGENTS.md")
    if os.path.exists(agents_md):
        os.remove(agents_md)
        print("  architect AGENTS.md removed")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)
        print("  skill claw-forge removed")

    db_path = os.path.join(SCRIPT_DIR, "clawforge.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  registry removed")

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
