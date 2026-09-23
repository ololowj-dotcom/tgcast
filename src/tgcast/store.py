from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_RUNS = 50


class History:
    def __init__(self, path: Optional[Path], data: Optional[Dict[str, Any]] = None):
        self.path = path
        self.data: Dict[str, Any] = data or {}
        self.data.setdefault("version", 1)
        self.data.setdefault("sent", {})
        self.data.setdefault("runs", [])

    @classmethod
    def load(cls, path: Optional[Path]) -> History:
        if path is None or not Path(path).exists():
            return cls(path)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not an object")
            return cls(path, raw)
        except (OSError, ValueError):
            broken = Path(str(path) + ".corrupt")
            try:
                os.replace(path, broken)
            except OSError:
                pass
            history = cls(path)
            history.recovered = True
            return history

    recovered = False

    def save(self) -> None:
        if self.path is None:
            return
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def last_sent(self, chat_id: int) -> Optional[float]:
        entry = self.data["sent"].get(str(chat_id))
        return float(entry["ts"]) if entry else None

    def record_sent(self, chat_id: int, title: str, ts: float, message_id: Optional[int]) -> None:
        self.data["sent"][str(chat_id)] = {"ts": ts, "title": title, "message_id": message_id}
        self.save()

    def add_run(self, summary: Dict[str, Any]) -> None:
        self.data["runs"].append(summary)
        del self.data["runs"][:-MAX_RUNS]
        self.save()

    @property
    def runs(self) -> List[Dict[str, Any]]:
        return self.data["runs"]

    @property
    def sent(self) -> Dict[str, Dict[str, Any]]:
        return self.data["sent"]
