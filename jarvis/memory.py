"""Only explicit user memory commands can cause durable writes."""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def memory_command(text: str):
    match = re.match(r"^\s*(?:bunu\s+hatırla|şunu\s+hatırla)\s*[:;,]?\s+(.+)$", text, re.I)
    if match:
        note = match.group(1).strip()
        return ("add", note[:500]) if note else ("empty", "")
    if re.fullmatch(r"\s*(?:bunu|şunu)\s+hatırla[.!]?\s*", text, re.I):
        return "empty", ""
    if re.fullmatch(r"\s*(?:neleri hatırlıyorsun|hatırladıklarını söyle|hatıralarımı göster)[?!.]?\s*", text, re.I):
        return "list", ""
    if re.fullmatch(r"\s*(?:bütün|tüm) (?:hatıralarımı|kayıtlı notlarımı) sil[.!]?\s*", text, re.I):
        return "delete_all", ""
    return None


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise RuntimeError("Hatıra veritabanı bu uygulamadan daha yeni bir sürüme ait.")
        self.db.execute("CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL, source_turn_id TEXT NOT NULL)")
        self.db.execute("PRAGMA user_version=1")
        self.db.commit()

    def add(self, text: str, turn_id: str):
        self.db.execute("INSERT INTO memories(text, created_at, source_turn_id) VALUES(?,?,?)", (text[:500], datetime.now(timezone.utc).isoformat(), turn_id))
        self.db.commit()

    def list(self):
        rows = self.db.execute("SELECT id,text FROM memories ORDER BY id DESC LIMIT 30").fetchall()
        return [{"id": row[0], "text": row[1]} for row in rows]

    def delete_all(self):
        self.db.execute("DELETE FROM memories")
        self.db.commit()

    def close(self):
        self.db.close()
