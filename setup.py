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


def run_cmd(cmd):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        print(f"  WARN: {result.stderr.strip()}")
    return result.returncode == 0


def install():
    print("=== ClawForge Setup ===\n")

    total_steps = len(BASE_AGENTS) + 3

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

    # 2. Orchestrator SOUL.md
    step = len(BASE_AGENTS) + 1
    print(f"[{step}/{total_steps}] Configuring orchestrator...")
    src_soul = os.path.join(SCRIPT_DIR, "agents", "orchestrator", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
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

    print(f"\n=== ClawForge installed! ===")
    print(f"Base agents: {len(BASE_AGENTS) + 1} (orchestrator + {', '.join(BASE_AGENTS)})")
    print(f'Send your bot a message: "what agents do you have?"')


def update():
    print("=== ClawForge Update ===\n")

    for agent in BASE_AGENTS:
        workspace = os.path.join(WORKSPACES_DIR, agent)
        src_soul = os.path.join(SCRIPT_DIR, "agents", agent, "SOUL.md")
        dst_soul = os.path.join(workspace, "SOUL.md")
        if os.path.exists(workspace):
            shutil.copy2(src_soul, dst_soul)
            print(f"  {agent} SOUL.md updated")

    src_soul = os.path.join(SCRIPT_DIR, "agents", "orchestrator", "SOUL.md")
    dst_soul = os.path.join(MAIN_WORKSPACE, "SOUL.md")
    shutil.copy2(src_soul, dst_soul)
    print("  orchestrator SOUL.md updated")

    skill_dir = os.path.join(MAIN_WORKSPACE, "skills", "claw-forge")
    os.makedirs(skill_dir, exist_ok=True)
    src_skill = os.path.join(SCRIPT_DIR, "skills", "claw-forge", "SKILL.md")
    dst_skill = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(src_skill, dst_skill)
    print("  skill claw-forge updated")

    print("\n=== Update complete ===")


def uninstall():
    print("=== ClawForge Uninstall ===\n")

    for agent in BASE_AGENTS:
        print(f"  Removing agent {agent}...")
        run_cmd(f"openclaw agents delete {agent} --yes")
        workspace = os.path.join(WORKSPACES_DIR, agent)
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        print(f"  done")

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
