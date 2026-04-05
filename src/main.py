#!/usr/bin/env python3
"""ClawForge CLI — architect layer for OpenClaw agent management."""

import argparse
import datetime
import json
import signal
import sys
import os
import time

# Allow running as script from any location
sys.path.insert(0, os.path.dirname(__file__))

import registry
import orchestration
import deploy
import versioning


PIPELINE_PID_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "pipeline.pid")


def save_pipeline_pid(pid, agent_name=None):
    """Save pipeline PID to file."""
    os.makedirs(os.path.dirname(PIPELINE_PID_FILE), exist_ok=True)
    data = {
        "pid": pid,
        "started_at": datetime.datetime.now().isoformat()
    }
    if agent_name:
        data["agent_name"] = agent_name
    with open(PIPELINE_PID_FILE, "w") as f:
        json.dump(data, f)


def read_pipeline_pid():
    """Read pipeline PID file. Returns dict or None."""
    try:
        with open(PIPELINE_PID_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def remove_pipeline_pid():
    """Remove pipeline PID file."""
    try:
        os.remove(PIPELINE_PID_FILE)
    except FileNotFoundError:
        pass


def is_pipeline_running():
    """Check if a pipeline is currently running."""
    data = read_pipeline_pid()
    if not data:
        return False
    try:
        os.kill(data["pid"], 0)
        return True
    except (OSError, ProcessLookupError):
        remove_pipeline_pid()
        return False


def cmd_create(args):
    try:
        secrets = json.loads(args.secrets)
        if not isinstance(secrets, dict):
            raise ValueError("secrets must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Invalid --secrets JSON: {e}")
        sys.exit(1)

    if args.notify:
        channel, user_id = args.notify.split(":")

        # Check if pipeline already running
        if is_pipeline_running():
            print("Конвейер уже работает. Напиши «отмена» чтобы остановить.")
            return

        pid = os.fork()
        if pid > 0:
            # Parent: return immediately (architect sends confirmation via SKILL.md)
            return
        # Child: clear old sessions and run pipeline
        deploy.clear_pipeline_sessions()
        save_pipeline_pid(os.getpid())
        try:
            result = orchestration.run_pipeline(args.task, secrets)
            msg = result.get("message", "Конвейер завершён.")
            deploy.send_notification(channel, user_id, msg)
            if result.get("action") in ("created", "extended") and result.get("needs_heartbeat"):
                time.sleep(2)
                try:
                    deploy.run_cmd("openclaw gateway restart")
                except RuntimeError:
                    pass
        except Exception as e:
            deploy.send_notification(channel, user_id, f"Ошибка при создании агента: {str(e)[:300]}")
        finally:
            remove_pipeline_pid()
            os._exit(0)
    else:
        result = orchestration.run_pipeline(args.task, secrets)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_cancel(args):
    data = read_pipeline_pid()
    if not data:
        print("Нет активного конвейера.")
        return

    pid = data["pid"]

    # Check if process is alive
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        remove_pipeline_pid()
        print("Конвейер уже завершился.")
        return

    # Kill the process and wait for termination
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    for _ in range(10):
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except (OSError, ProcessLookupError):
            break
    else:
        # Still alive after 5s — force kill
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    # Cleanup partial artifacts
    agent_name = data.get("agent_name")
    if agent_name:
        agent = registry.get_agent(agent_name)
        if agent:
            try:
                deploy.delete_agent(agent_name)
            except Exception as e:
                print(f"Ошибка при очистке артефактов: {str(e)[:200]}")
            registry.remove_agent(agent_name)

    remove_pipeline_pid()

    if args.notify:
        channel, user_id = args.notify.split(":")
        deploy.send_notification(channel, user_id, "Создание агента отменено.")
    print("Конвейер остановлен.")


def cmd_list(args):
    registry.sync_with_openclaw()
    agents = registry.list_agents()
    if not agents:
        print("Реестр пуст. Агенты ещё не создавались.")
        return
    for a in agents:
        print(f"- {a['name']} ({a['type']}): {a['description']}")
        print(f"  Capabilities: {', '.join(a['capabilities'])}")
        print(f"  Создан: {a['created_at']}")
        print()


def cmd_search(args):
    agents = registry.search_agents(args.query)
    if not agents:
        print(f"Ничего не найдено по запросу: {args.query}")
        return
    for a in agents:
        print(f"- {a['name']}: {a['description']}")


def cmd_bind(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    telegram_user_id = deploy.get_telegram_user_id()
    deploy.bind_agent_to_bot(args.agent, args.token, telegram_user_id)

    # Gateway hot-reloads after config change, which can interrupt
    # the architect's response delivery. Send explicit notification.
    time.sleep(2)
    deploy.send_notification(
        "telegram", telegram_user_id,
        f"Бот привязан к агенту {args.agent}. Можешь писать ему напрямую."
    )
    print(f"Бот привязан к агенту: {args.agent}")


def cmd_delete(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    deploy.delete_agent(args.agent)
    registry.remove_agent(args.agent)

    # Gateway hot-reloads after unbind + restart after cron cleanup.
    # 5s ensures gateway fully restarts before send_notification.
    time.sleep(5)
    deploy.send_notification(
        "telegram", deploy.get_telegram_user_id(),
        f"Агент '{args.agent}' удалён."
    )
    print(f"Агент '{args.agent}' удалён.")


def cmd_snapshot(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    version = versioning.create_snapshot(args.agent, "quick_fix", args.comment)
    if version is None:
        print(f"Не удалось создать снапшот: workspace агента '{args.agent}' не найден.")
        sys.exit(1)

    print(f"Снапшот создан: v{version['number']} ({version['id']})")
    print(f"Комментарий: {version['comment']}")


def _format_source(source):
    labels = {
        "created": "создан",
        "extend_existing": "extend",
        "quick_fix": "quick fix"
    }
    return labels.get(source, source)


def _format_date(iso_timestamp):
    """Format ISO timestamp to readable dd.MM.yyyy HH:MM."""
    try:
        dt = datetime.datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso_timestamp


def cmd_history(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    if args.version:
        info = versioning.get_version_info(args.agent, args.version)
        if not info:
            print(f"Версия {args.version} не найдена.")
            sys.exit(1)
        v = info["version"]
        print(f"{args.agent} v{v['number']} ({_format_source(v['source'])}) — {_format_date(v['created_at'])}")
        if info["is_current"]:
            print("  (текущая)")
        print()
        print(f"Комментарий: {v['comment']}")
        print(f"Создан: {v['source']}")
        if v.get("changed_files"):
            print(f"Изменено: {', '.join(v['changed_files'])}")
        print()
        cron = info["cron"]
        if cron:
            schedule = cron.get("schedule", {})
            print(f"Cron: {schedule.get('expr', '?')} {schedule.get('tz', '')}, enabled={cron.get('enabled', False)}")
        else:
            print("Cron: нет")
        print()
        print("Файлы:")
        for f in info["files"]:
            size_kb = f["size"] / 1024
            print(f"  {f['path']} ({size_kb:.1f} KB)")
        return

    manifest = versioning.list_versions(args.agent)
    if not manifest["versions"]:
        print(f"История {args.agent} пуста.")
        return

    current_id = manifest.get("current")
    current_num = None
    for v in manifest["versions"]:
        if v["id"] == current_id:
            current_num = v["number"]
            break

    print(f"История {args.agent} (текущая: v{current_num}):" if current_num else f"История {args.agent}:")
    print()
    for v in manifest["versions"]:
        marker = "  ← текущая" if v["id"] == current_id else ""
        print(f"v{v['number']} ({_format_source(v['source'])}) — {_format_date(v['created_at'])}{marker}")
        print(f"  Комментарий: {v['comment']}")
        if v.get("changed_files"):
            print(f"  Изменено: {', '.join(v['changed_files'])}")
        print()
    print(f"Откатить: python3 main.py rollback --agent {args.agent} --version <номер>")


def cmd_rollback(args):
    agent = registry.get_agent(args.agent)
    if not agent:
        print(f"Агент '{args.agent}' не найден в реестре.")
        sys.exit(1)

    result = versioning.rollback_to_version(args.agent, args.version)
    if result["status"] == "error":
        print(result["reason"])
        sys.exit(1)

    target = result["version"]
    print(f"Готово. Текущая версия {args.agent} — v{target['number']}.")

    # Gateway restart if cron changed
    if result["cron_changed"]:
        try:
            deploy.run_cmd("openclaw gateway restart")
        except RuntimeError as e:
            print(f"Warning: gateway restart failed: {e}")

    if args.notify:
        channel, user_id = args.notify.split(":")
        deploy.send_notification(
            channel, user_id,
            f"Агент '{args.agent}' откачен на v{target['number']}."
        )


def main():
    registry.init_db()
    parser = argparse.ArgumentParser(description="ClawForge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create", help="Create a new agent from task description")
    p_create.add_argument("--task", required=True, help="Task description")
    p_create.add_argument("--notify", help="Notify target after completion (e.g. telegram:541534272)")
    p_create.add_argument("--secrets", default="{}", help="JSON object with secrets to substitute into agent artifacts")
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

    p_cancel = subparsers.add_parser("cancel", help="Cancel running pipeline")
    p_cancel.add_argument("--notify", help="Notify target after cancellation")
    p_cancel.set_defaults(func=cmd_cancel)

    p_snapshot = subparsers.add_parser("snapshot", help="Create a manual snapshot of agent")
    p_snapshot.add_argument("--agent", required=True, help="Agent name")
    p_snapshot.add_argument("--comment", required=True, help="Description of changes")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_history = subparsers.add_parser("history", help="Show agent version history")
    p_history.add_argument("--agent", required=True, help="Agent name")
    p_history.add_argument("--version", help="Show details for specific version (number or id or 'previous')")
    p_history.set_defaults(func=cmd_history)

    p_rollback = subparsers.add_parser("rollback", help="Rollback agent to previous version")
    p_rollback.add_argument("--agent", required=True, help="Agent name")
    p_rollback.add_argument("--version", required=True, help="Target version (number, id, or 'previous')")
    p_rollback.add_argument("--notify", help="Notify target after completion")
    p_rollback.set_defaults(func=cmd_rollback)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
