#!/usr/bin/env python3
"""ClawForge CLI — architect layer for OpenClaw agent management."""

import argparse
import json
import sys
import os

# Allow running as script from any location
sys.path.insert(0, os.path.dirname(__file__))

import registry
import orchestration
import deploy


def cmd_create(args):
    registry.init_db()
    result = orchestration.run_pipeline(args.task)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list(args):
    registry.init_db()
    agents = registry.list_agents()
    if not agents:
        print("Реестр пуст. Агенты ещё не создавались.")
        return
    for a in agents:
        caps = json.loads(a["capabilities"]) if isinstance(a["capabilities"], str) else a["capabilities"]
        print(f"- {a['name']} ({a['type']}): {a['description']}")
        print(f"  Capabilities: {', '.join(caps)}")
        print(f"  Создан: {a['created_at']}")
        print()


def cmd_search(args):
    registry.init_db()
    agents = registry.search_agents(args.query)
    if not agents:
        print(f"Ничего не найдено по запросу: {args.query}")
        return
    for a in agents:
        print(f"- {a['name']}: {a['description']}")


def cmd_switch(args):
    telegram_user_id = os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")
    deploy.switch_agent(args.agent, telegram_user_id)
    print(f"Переключено на агента: {args.agent}")


def cmd_delete(args):
    registry.init_db()
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    deploy.delete_agent(args.agent)
    registry.remove_agent(args.agent)
    print(f"Агент '{args.agent}' удалён.")


def main():
    parser = argparse.ArgumentParser(description="ClawForge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create", help="Create a new agent from task description")
    p_create.add_argument("--task", required=True, help="Task description")
    p_create.set_defaults(func=cmd_create)

    p_list = subparsers.add_parser("list", help="List all agents in registry")
    p_list.set_defaults(func=cmd_list)

    p_search = subparsers.add_parser("search", help="Search agents by query")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.set_defaults(func=cmd_search)

    p_switch = subparsers.add_parser("switch", help="Switch Telegram to a different agent")
    p_switch.add_argument("--agent", required=True, help="Agent name")
    p_switch.set_defaults(func=cmd_switch)

    p_delete = subparsers.add_parser("delete", help="Delete an agent")
    p_delete.add_argument("--agent", required=True, help="Agent name")
    p_delete.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
