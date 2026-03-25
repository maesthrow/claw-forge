"""ClawForge agent registry — SQLite storage for agent metadata."""

import sqlite3
import json
import os
import datetime
import subprocess

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "clawforge.db")

ALLOWED_COLUMNS = {"description", "capabilities", "workspace_path", "parent_agent"}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                parent_agent TEXT,
                workspace_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def add_agent(name, agent_type, description, capabilities, workspace_path, parent_agent=None):
    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agents (name, type, description, capabilities, parent_agent, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, agent_type, description, json.dumps(capabilities, ensure_ascii=False), parent_agent, workspace_path, now, now)
        )


def remove_agent(name):
    with get_connection() as conn:
        conn.execute("DELETE FROM agents WHERE name = ?", (name,))


def update_agent(name, **kwargs):
    if not kwargs:
        return
    for key in kwargs:
        if key not in ALLOWED_COLUMNS:
            raise ValueError(f"Invalid column: {key}")

    now = datetime.datetime.now().isoformat()
    updates = {}
    for key, value in kwargs.items():
        if key == "capabilities":
            value = json.dumps(value, ensure_ascii=False)
        updates[key] = value
    updates["updated_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [name]
    with get_connection() as conn:
        conn.execute(f"UPDATE agents SET {set_clause} WHERE name = ?", values)


def _deserialize_agent(row):
    """Convert a DB row to dict with capabilities parsed from JSON string to list."""
    agent = dict(row)
    caps = agent.get("capabilities")
    if isinstance(caps, str):
        agent["capabilities"] = json.loads(caps)
    return agent


def get_agent(name):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        if row:
            return _deserialize_agent(row)
        return None


def list_agents():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        return [_deserialize_agent(r) for r in rows]


def search_agents(query):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agents WHERE description LIKE ? OR capabilities LIKE ?",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
        return [_deserialize_agent(r) for r in rows]


def sync_with_openclaw():
    """Remove registry entries for agents that no longer exist in OpenClaw."""
    try:
        result = subprocess.run(
            "openclaw agents list --json",
            shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return

        # Extract agent IDs from JSON output
        agents_data = json.loads(result.stdout)
        openclaw_ids = {a["id"] for a in agents_data if "id" in a}
        # Only check agents that ARE in our registry
        with get_connection() as conn:
            rows = conn.execute("SELECT name FROM agents").fetchall()
            for row in rows:
                name = row["name"]
                if name not in openclaw_ids:
                    conn.execute("DELETE FROM agents WHERE name = ?", (name,))
    except Exception:
        pass  # best-effort sync
