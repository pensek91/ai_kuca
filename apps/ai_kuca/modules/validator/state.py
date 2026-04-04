import json
import os
import fcntl
from typing import Any


class ValidatorStateStore:
    def __init__(self, state_path: str, log_fn):
        self.state_path = state_path
        self.log = log_fn

    def _lock_path(self) -> str:
        return f"{self.state_path}.lock"

    def load(self) -> dict[str, Any]:
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self._lock_path(), "a", encoding="utf-8") as lock_f:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                try:
                    if not os.path.exists(self.state_path):
                        return {}
                    with open(self.state_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                    return data if isinstance(data, dict) else {}
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except Exception:
            return {}

    def save(self, state: dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self._lock_path(), "a", encoding="utf-8") as lock_f:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                try:
                    tmp_path = f"{self.state_path}.{os.getpid()}.tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(state or {}, f, ensure_ascii=True)
                    os.replace(tmp_path, self.state_path)
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            return True
        except Exception as ex:
            self.log(f"[CONFIG] Unable to persist validator state: {ex}", level="WARNING")
            return False

    def mark_write(self, source: str, ts: float) -> None:
        state = self.load()
        state["last_write_ts"] = float(ts)
        state["last_write_source"] = str(source)
        self.save(state)
