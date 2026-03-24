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

    if args.notify:
        # Background mode: fork and return immediately
        channel, user_id = args.notify.split(":")
        pid = os.fork()
        if pid > 0:
            # Parent: return immediately
            print("Конвейер создания запущен в фоне. Результат придёт в чат.")
            return
        # Child: run pipeline and notify
        try:
            result = orchestration.run_pipeline(args.task)
            msg = result.get("message", "Конвейер завершён.")
            if result.get("action") == "created":
                msg += f"\nАгент {result['agent_name']} создан. Чтобы общаться с ним напрямую — создай бота в @BotFather и пришли мне токен."
            elif result.get("action") == "extended":
                msg += f"\nАгент {result['agent_name']} расширен."
            elif result.get("action") == "reuse":
                msg += f"\nДля этой задачи подходит агент {result['agent_name']}."
            deploy.send_notification(channel, user_id, msg)
        except Exception as e:
            deploy.send_notification(channel, user_id, f"Ошибка при создании агента: {str(e)[:300]}")
        finally:
            os._exit(0)
    else:
        # Sync mode (for debugging)
        result = orchestration.run_pipeline(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list(args):
    registry.init_db()
    registry.sync_with_openclaw()
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


def _get_telegram_user_id():
    """Get Telegram user ID from config file or environment."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".telegram_id")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            tid = f.read().strip()
            if tid:
                return tid
    return os.environ.get("CLAWFORGE_TELEGRAM_USER_ID", "541534272")


def cmd_bind(args):
    registry.init_db()
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)
    deploy.bind_agent_to_bot(args.agent, args.token, _get_telegram_user_id())
    print(f"Бот привязан к агенту: {args.agent}")


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
    p_create.add_argument("--notify", help="Notify target after completion (e.g. telegram:541534272)")
    p_create.set_defaults(func=cmd_create)

    p_list = subparsers.add_parser("list", help="List all agents in registry")
    p_list.set_defaults(func=cmd_list)

    p_search = subparsers.add_parser("search", help="Search agents by query")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.set_defaults(func=cmd_search)

    p_bind = subparsers.add_parser("bind", help="Bind a Telegram bot to an agent")
    p_bind.add_argument("--agent", required=True, help="Agent name")
    p_bind.add_argument("--token", required=True, help="Telegram bot token from BotFather")
    p_bind.set_defaults(func=cmd_bind)

    p_delete = subparsers.add_parser("delete", help="Delete an agent")
    p_delete.add_argument("--agent", required=True, help="Agent name")
    p_delete.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
