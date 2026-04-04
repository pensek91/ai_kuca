import time


class RuntimeWatcher:
    def __init__(self, state_store, guardrails, compute_hash, validate_config, logger):
        self.state_store = state_store
        self.guardrails = guardrails
        self.compute_hash = compute_hash
        self.validate_config = validate_config
        self.log = logger

    def process(self, source="runtime_event", dry_run=False):
        if self.guardrails.in_own_write_window():
            self.log("[CONFIG] Runtime watcher suppressed (own write window)", level="DEBUG")
            return

        state = self.state_store.load()
        current_hash = self.compute_hash()
        if current_hash == state.get("last_hash"):
            self.log("[CONFIG] Runtime watcher skip: no config diff", level="DEBUG")
            return

        allowed, history_10m = self.guardrails.allow_apply(state)
        if not allowed:
            self.log("[CONFIG] Runtime watcher rate-limited", level="WARNING")
            return

        self.log(f"[CONFIG] Runtime watcher apply | source={source}", level="INFO")
        if dry_run:
            self.log("[CONFIG] dry_run=true -> runtime watcher would validate and mark dirty UI", level="INFO")
            return

        self.validate_config({})
        history_10m.append(time.time())
        state["apply_history"] = history_10m
        state["last_hash"] = current_hash
        state["last_apply_ts"] = time.time()
        state["source"] = str(source)
        state["dirty_ui"] = True
        self.state_store.save(state)
