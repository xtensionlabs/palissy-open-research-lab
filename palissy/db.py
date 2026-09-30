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
    created_at REAL NOT NULL, notebook_path TEXT, error TEXT, state TEXT
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
CREATE TABLE IF NOT EXISTS gates (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, cycle INTEGER NOT NULL, stage TEXT NOT NULL,
    title TEXT NOT NULL, proposal TEXT NOT NULL, status TEXT NOT NULL,
    created_at REAL NOT NULL, resolved_at REAL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(project_id, ts);
"""


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Used only from the asyncio event loop; check_same_thread=False lets test clients
        # and uvicorn's loop thread share it.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
        for col in ("error", "state"):  # databases created before these columns existed
            if col not in cols:
                self.conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
        self.conn.commit()

    def create_project(self, question: str) -> str:
        pid = uuid.uuid4().hex[:8]
        self.conn.execute(
            "INSERT INTO projects (id, question, status, created_at) VALUES (?,?,?,?)",
            (pid, question, "running", time.time()),
        )
        self.conn.commit()
        return pid

    def update_project(self, pid: str, *, status: str | None = None,
                       notebook_path: str | None = None, error: str | None = None) -> None:
        if status:
            self.conn.execute("UPDATE projects SET status=? WHERE id=?", (status, pid))
        if error:
            self.conn.execute("UPDATE projects SET error=? WHERE id=?", (error, pid))
        if notebook_path:
            self.conn.execute("UPDATE projects SET notebook_path=? WHERE id=?",
                              (notebook_path, pid))
        self.conn.commit()

    def save_state(self, pid: str, state: dict) -> None:
        """Snapshot of the current cycle (hypothesis, code, verdict, lessons...) for the UI."""
        self.conn.execute("UPDATE projects SET state=? WHERE id=?",
                          (json.dumps(state, default=str), pid))
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

    # --- gates: pending human decisions, persisted so a page refresh can find them ---------

    def create_gate(self, project_id: str, cycle: int, stage: str, title: str,
                    proposal: dict) -> str:
        gid = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO gates (id, project_id, cycle, stage, title, proposal, status, "
            "created_at) VALUES (?,?,?,?,?,?,?,?)",
            (gid, project_id, cycle, stage, title, json.dumps(proposal, default=str),
             "pending", time.time()))
        self.conn.commit()
        return gid

    def get_gate(self, gate_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM gates WHERE id=?", (gate_id,)).fetchone()
        return self._gate(row) if row else None

    def pending_gate(self, project_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM gates WHERE project_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        return self._gate(row) if row else None

    def resolve_gate(self, gate_id: str, status: str = "resolved") -> None:
        self.conn.execute("UPDATE gates SET status=?, resolved_at=? WHERE id=?",
                          (status, time.time(), gate_id))
        self.conn.commit()

    def interrupt_running(self) -> int:
        """On startup: runs whose process died can never finish; make that visible."""
        cur = self.conn.execute(
            "UPDATE projects SET status='interrupted', error='server restarted mid-run' "
            "WHERE status='running'")
        self.conn.execute("UPDATE gates SET status='abandoned' WHERE status='pending'")
        self.conn.commit()
        return cur.rowcount

    def cost_by_model(self, project_id: str | None = None) -> list[dict]:
        where, args = ("WHERE project_id=?", (project_id,)) if project_id else ("", ())
        rows = self.conn.execute(
            f"SELECT COALESCE(model,'(tool)') AS model, kind, COUNT(*) AS calls, "
            f"SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out, "
            f"SUM(cost_usd) AS cost_usd, SUM(latency_s) AS latency_s FROM records {where} "
            f"GROUP BY model, kind ORDER BY cost_usd DESC", args).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _gate(row) -> dict:
        d = dict(row)
        d["proposal"] = json.loads(d["proposal"])
        return d

    def kv_get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)",
                          (key, json.dumps(value)))
        self.conn.commit()
