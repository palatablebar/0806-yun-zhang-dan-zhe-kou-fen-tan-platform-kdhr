import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS carries (
    id TEXT PRIMARY KEY, report TEXT NOT NULL,
    source_run_id TEXT NOT NULL, target_period TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created TEXT NOT NULL, issued TEXT,
    revision INTEGER NOT NULL DEFAULT 0
);"""


class CarryStore:
    """下月结转批次的持久化。与 runs 库同文件，复用 SQLite 事务保证原子切换。"""

    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute(SCHEMA)
            yield db

    def register(self, carry_id, report):
        with self.connect() as db:
            db.execute(
                "INSERT INTO carries(id,report,source_run_id,target_period,status,created)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (
                    carry_id,
                    json.dumps(report, ensure_ascii=False),
                    report["source_run_id"],
                    report["target_period"],
                    report["status"],
                    report["created"],
                ),
            )
        return self.load(carry_id)

    def save(self, carry):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE carries SET report=?, status=?, revision=? WHERE id=?",
                (
                    json.dumps(carry["report"], ensure_ascii=False),
                    carry["report"]["status"],
                    carry["revision"],
                    carry["id"],
                ),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("CARRY_NOT_FOUND")
        return self.load(carry["id"])

    def load(self, carry_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM carries WHERE id=?", (carry_id,)).fetchone()
        if row is None:
            raise DomainIssue("CARRY_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,source_run_id,target_period,status,created,issued,revision"
                    " FROM carries ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def issue(self, carry_id, report, issued_at):
        """单条条件 UPDATE 完成原子签发：报告与状态同事务写入。

        并发下只有一个执行者能把非 ISSUED 行切为 ISSUED，失败则整批保持原样。
        """
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE carries SET report=?, status='ISSUED', issued=?,"
                " revision=revision+1 WHERE id=? AND status!='ISSUED'",
                (json.dumps(report, ensure_ascii=False), issued_at, carry_id),
            )
            if cursor.rowcount != 1:
                row = db.execute("SELECT status FROM carries WHERE id=?", (carry_id,)).fetchone()
                if row is None:
                    raise DomainIssue("CARRY_NOT_FOUND")
                raise DomainIssue("CARRY_FINALIZED")
        return self.load(carry_id)
