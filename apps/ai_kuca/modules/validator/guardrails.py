import time


class ValidatorGuardrails:
    def __init__(self, state_store, own_write_window_sec=5.0, max_apply_per_30s=1, max_apply_per_10m=3):
        self.state_store = state_store
        self.own_write_window_sec = float(own_write_window_sec)
        self.max_apply_per_30s = int(max_apply_per_30s)
        self.max_apply_per_10m = int(max_apply_per_10m)

    def in_own_write_window(self, now=None) -> bool:
        now = time.time() if now is None else float(now)
        state = self.state_store.load()
        last_write_ts = float(state.get("last_write_ts", 0) or 0)
        return (now - last_write_ts) <= self.own_write_window_sec

    def allow_apply(self, state: dict, now=None) -> tuple[bool, list[float]]:
        now = time.time() if now is None else float(now)
        history = [float(x) for x in (state.get("apply_history") or []) if isinstance(x, (int, float))]
        history_10m = [x for x in history if now - x <= 600]
        history_30s = [x for x in history if now - x <= 30]

        if len(history_30s) >= self.max_apply_per_30s:
            return False, history_10m
        if len(history_10m) >= self.max_apply_per_10m:
            return False, history_10m
        return True, history_10m
