"""ClawForge agent registry — SQLite storage for agent metadata."""

import sqlite3
import json
import os
import datetime

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
    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        for key, value in kwargs.items():
            if key not in ALLOWED_COLUMNS:
                raise ValueError(f"Invalid column: {key}")
            if key == "capabilities":
                value = json.dumps(value, ensure_ascii=False)
            conn.execute(f"UPDATE agents SET {key} = ?, updated_at = ? WHERE name = ?", (value, now, name))


def get_agent(name):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        if row:
            return dict(row)
        return None


def list_agents():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


def search_agents(query):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agents WHERE description LIKE ? OR capabilities LIKE ?",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
        return [dict(r) for r in rows]
