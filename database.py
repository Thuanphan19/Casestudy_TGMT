import sqlite3
import json
from datetime import datetime

DB_PATH = "peopletrack.db"

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

def get_history():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT filename, stats, created_at FROM history ORDER BY id DESC")
        return [
            {
                "filename": r[0], 
                "created_at": r[2], 
                **json.loads(r[1])
            } for r in cur.fetchall()
        ]