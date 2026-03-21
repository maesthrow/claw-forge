"""ClawForge agent registry — SQLite storage for agent metadata."""

import sqlite3
import json
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "clawforge.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
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
    conn.commit()
    conn.close()


def add_agent(name, agent_type, description, capabilities, workspace_path, parent_agent=None):
    conn = get_connection()
    now = datetime.datetime.now().isoformat()
    conn.execute(
        "INSERT INTO agents (name, type, description, capabilities, parent_agent, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, agent_type, description, json.dumps(capabilities, ensure_ascii=False), parent_agent, workspace_path, now, now)
    )
    conn.commit()
    conn.close()


def remove_agent(name):
    conn = get_connection()
    conn.execute("DELETE FROM agents WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def update_agent(name, **kwargs):
    conn = get_connection()
    now = datetime.datetime.now().isoformat()
    for key, value in kwargs.items():
        if key == "capabilities":
            value = json.dumps(value, ensure_ascii=False)
        conn.execute(f"UPDATE agents SET {key} = ?, updated_at = ? WHERE name = ?", (value, now, name))
    conn.commit()
    conn.close()


def get_agent(name):
    conn = get_connection()
    row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def list_agents():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_agents(query):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agents WHERE description LIKE ? OR capabilities LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
