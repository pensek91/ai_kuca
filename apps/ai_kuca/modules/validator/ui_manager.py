class UIManager:
    def __init__(
        self,
        state_store,
        compute_hash,
        get_mode,
        show_config,
        populate_dropdowns,
        load_values,
        update_options,
        logger,
    ):
        self.state_store = state_store
        self.compute_hash = compute_hash
        self.get_mode = get_mode
        self.show_config = show_config
        self.populate_dropdowns = populate_dropdowns
        self.load_values = load_values
        self.update_options = update_options
        self.log = logger

    def run(self, reason="dirty_flag", force=False, dry_run=False):
        state = self.state_store.load()
        current_hash = self.compute_hash()
        ui_hash = f"{current_hash}:{self.get_mode() or ''}"

        if not force and not state.get("dirty_ui") and state.get("last_ui_hash") == ui_hash:
            self.log(f"[CONFIG] UI manager skip: no UI changes | reason={reason}", level="DEBUG")
            return

        self.log(f"[CONFIG] UI manager apply | reason={reason}", level="INFO")
        if dry_run:
            self.log("[CONFIG] dry_run=true -> UI manager would refresh dropdowns/helpers", level="INFO")
            return

        self.show_config({})
        self.populate_dropdowns({})
        self.load_values({})
        self.update_options({})

        state["dirty_ui"] = False
        state["last_ui_hash"] = ui_hash
        self.state_store.save(state)
