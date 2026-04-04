import time


class StartupValidator:
    def __init__(
        self,
        state_store,
        ensure_helpers,
        ensure_room_targets,
        validate_config,
        validate_entities,
        compute_hash,
        logger,
    ):
        self.state_store = state_store
        self.ensure_helpers = ensure_helpers
        self.ensure_room_targets = ensure_room_targets
        self.validate_config = validate_config
        self.validate_entities = validate_entities
        self.compute_hash = compute_hash
        self.log = logger

    def run(self, dry_run=False):
        self.log("[CONFIG] Startup validator phase started", level="INFO")

        if dry_run:
            self.log("[CONFIG] dry_run=true -> startup validator would ensure helpers + validate config", level="INFO")
            return

        self.ensure_helpers()
        self.ensure_room_targets()
        self.validate_config({})
        self.validate_entities()

        state = self.state_store.load()
        state["last_hash"] = self.compute_hash()
        state["last_apply_ts"] = time.time()
        state["source"] = "startup"
        state["dirty_ui"] = True
        self.state_store.save(state)
        self.log("[CONFIG] Startup validator phase completed", level="INFO")
