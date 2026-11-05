import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "peopletrack.db"
HISTORY_DATE = "substr(created_at, 7, 4) || '-' || substr(created_at, 4, 2) || '-' || substr(created_at, 1, 2)"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                output_name TEXT,
                stats TEXT,
                processing_time REAL,
                created_at TEXT
            )
        """)

def save_history(filename, output_name, stats, processing_time):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO history (filename, output_name, stats, processing_time, created_at) VALUES (?, ?, ?, ?, ?)",
            (filename, output_name, json.dumps(stats), processing_time, datetime.now().strftime("%d/%m/%Y %H:%M"))
        )

def _date_filter(date):
    if not date:
        return "", []
    return f"{HISTORY_DATE} = ?", [date]

def get_history(date=None, limit=None, offset=0):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        query = (
            "SELECT id, filename, output_name, stats, processing_time, created_at "
            "FROM history"
        )
        date_condition, parameters = _date_filter(date)
        if date_condition:
            query += " WHERE " + date_condition
        query += " ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend((limit, offset))
        cur.execute(query, parameters)
        return [
            {
                "id": row[0],
                "filename": row[1],
                "output_name": row[2],
                "processing_time": row[4],
                "created_at": row[5],
                **json.loads(row[3]),
            }
            for row in cur.fetchall()
        ]

def count_history(date=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        query = "SELECT COUNT(*) FROM history"
        date_condition, parameters = _date_filter(date)
        if date_condition:
            query += " WHERE " + date_condition
        cur.execute(query, parameters)
        return cur.fetchone()[0]