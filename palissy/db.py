"""SQLite storage: projects, provenance records, human decisions, and a small kv store.

One connection, no infra. Records keep their full JSON in `data` so the provenance graph can be
rebuilt from parents without a schema per record kind.
"""

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .provenance import ProvenanceRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL,
    created_at REAL NOT NULL, notebook_path TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, cycle INTEGER NOT NULL,
    kind TEXT NOT NULL, stage TEXT NOT NULL, ts REAL NOT NULL, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_s REAL, data TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, cycle INTEGER NOT NULL, stage TEXT NOT NULL,
    proposal TEXT NOT NULL, action TEXT NOT NULL, payload TEXT, ts REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(project_id, ts);
"""


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def create_project(self, question: str) -> str:
        pid = uuid.uuid4().hex[:8]
        self.conn.execute(
            "INSERT INTO projects (id, question, status, created_at) VALUES (?,?,?,?)",
            (pid, question, "running", time.time()),
        )
        self.conn.commit()
        return pid

    def update_project(self, pid: str, *, status: str | None = None,
                       notebook_path: str | None = None) -> None:
        if status:
            self.conn.execute("UPDATE projects SET status=? WHERE id=?", (status, pid))
        if notebook_path:
            self.conn.execute("UPDATE projects SET notebook_path=? WHERE id=?",
                              (notebook_path, pid))
        self.conn.commit()

    def get_project(self, pid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()

    def add_record(self, r: ProvenanceRecord, project_id: str, cycle: int) -> None:
        self.conn.execute(
            "INSERT INTO records (id, project_id, cycle, kind, stage, ts, model, tokens_in, "
            "tokens_out, cost_usd, latency_s, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.id, project_id, cycle, r.kind, r.stage, r.ts, r.model, r.tokens_in,
             r.tokens_out, r.cost_usd, r.latency_s, json.dumps(asdict(r), default=str)),
        )
        self.conn.commit()

    def records(self, project_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT data FROM records WHERE project_id=? ORDER BY ts", (project_id,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def project_cost(self, project_id: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS c FROM records WHERE project_id=?",
            (project_id,)).fetchone()
        return row["c"]

    def add_decision(self, project_id: str, cycle: int, stage: str, proposal: dict,
                     action: str, payload: str | None) -> str:
        did = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO decisions (id, project_id, cycle, stage, proposal, action, payload, ts) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (did, project_id, cycle, stage, json.dumps(proposal, default=str), action,
             payload, time.time()),
        )
        self.conn.commit()
        return did

    def decisions(self, project_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE project_id=? ORDER BY ts", (project_id,)).fetchall()
        return [dict(r) for r in rows]

    def kv_get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)",
                          (key, json.dumps(value)))
        self.conn.commit()
