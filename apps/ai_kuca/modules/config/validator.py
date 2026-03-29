import os
from datetime import datetime, timezone
import time
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class AIConfigValidator(hass.Hass):
    """Proverava konfiguraciju pre pokretanja ostalih AI_KUCA aplikacija.

    Svaki put kada se pokrene, proverava `system_configs.yaml` i `room_configs.yaml`
    da li sadrĹľe obavezne kljueve i
    logira rezultat u Home Assistant.

    Ako nedostaju obavezni stavci, upisuje ERROR u log i u posebni status senzor.
    """

    def initialize(self):
        # === Popuni ai_kuca_duration_select s trajanjem boosta ===
        try:
            duration_options = ["NONE", "5 minuta", "15 minuta", "30 minuta", "60 minuta", "120 minuta"]
            self.call_service(
                "input_select/set_options",
                entity_id="input_select.ai_kuca_duration_select",
                options=duration_options
            )
        except Exception as e:
            self.log(f"[CONFIG] Greška pri popunjavanju ai_kuca_duration_select: {e}", level="ERROR")
        # === Popuni ai_kuca_boost_select s imenima soba iz room_configs.yaml ===
        try:
            room_cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "room_configs.yaml"))
            with open(room_cfg_path, "r", encoding="utf-8") as f:
                room_cfg = yaml.safe_load(f) or {}
            room_names = list(room_cfg.keys())
            boost_options = ["NONE"] + room_names
            self.call_service(
                "input_select/set_options",
                entity_id="input_select.ai_kuca_boost_select",
                options=boost_options
            )
        except Exception as e:
            self.log(f"[CONFIG] Greška pri popunjavanju ai_kuca_boost_select: {e}", level="ERROR")
            # --- Definicije helper entiteta (mora biti prije korištenja u ostatku koda) ---
        # input_boolean
        self.ai_heating_active = "input_boolean.ai_heating_active"
        self.ai_heating_eco = "input_boolean.ai_heating_eco"
        self.ai_kuca_reload_config = "input_boolean.ai_kuca_reload_config"
        self.ai_kuca_generate_config = "input_boolean.ai_kuca_generate_config"
        self.ai_kuca_room_builder_generate = "input_boolean.ai_kuca_room_builder_generate"
        self.ai_kuca_room_builder_delete = "input_boolean.ai_kuca_room_builder_delete"

        # input_text
        self.ai_kuca_system_config = "input_text.ai_kuca_system_config"
        self.ai_kuca_room_config = "input_text.ai_kuca_room_config"
        self.ai_kuca_room_builder_name = "input_text.ai_kuca_room_builder_name"
        self.ai_kuca_room_builder_target = "input_text.ai_kuca_room_builder_target"
        self.ai_kuca_room_builder_windows = "input_text.ai_kuca_room_builder_windows"
        self.ai_kuca_outdoor_temp_sensors = "input_text.ai_kuca_outdoor_temp_sensors"
        self.ai_kuca_climate_entities = "input_text.ai_kuca_climate_entities"

        # input_select
        self.ai_kuca_config_mode = "input_select.ai_kuca_config_mode"
        self.ai_kuca_room_select = "input_select.ai_kuca_room_select"
        self.ai_kuca_heating_flow_sensor = "input_select.ai_kuca_heating_flow_sensor"
        self.ai_kuca_heating_boiler_sensor = "input_select.ai_kuca_heating_boiler_sensor"
        self.ai_kuca_heating_outdoor_sensor = "input_select.ai_kuca_heating_outdoor_sensor"
        self.ai_kuca_heating_active_switch = "input_select.ai_kuca_heating_active_switch"
        self.ai_kuca_heating_eco_switch = "input_select.ai_kuca_heating_eco_switch"
        self.ai_kuca_heating_overheat_switch = "input_select.ai_kuca_heating_overheat_switch"
        self.ai_kuca_pump_switch = "input_select.ai_kuca_pump_switch"
        self.ai_kuca_valve_pause = "input_select.ai_kuca_valve_pause"
        self.ai_kuca_valve_open = "input_select.ai_kuca_valve_open"
        self.ai_kuca_valve_close = "input_select.ai_kuca_valve_close"
        self.ai_kuca_flow_sensor_2 = "input_select.ai_kuca_flow_sensor_2"
        self.ai_kuca_target_sensor = "input_select.ai_kuca_target_sensor"
        self.ai_kuca_room_builder_climate = "input_select.ai_kuca_room_builder_climate"
        self.ai_kuca_room_builder_temp_sensor = "input_select.ai_kuca_room_builder_temp_sensor"
        self.ai_kuca_room_builder_humidity_sensor = "input_select.ai_kuca_room_builder_humidity_sensor"
        self.ai_kuca_room_builder_fan = "input_select.ai_kuca_room_builder_fan"
        self.boost_soba = "input_select.boost_soba"
        self.turbo_boost_duration = "input_select.turbo_boost_duration"
        self.ai_kuca_boost_select = "input_select.ai_kuca_boost_select"
        self.ai_kuca_duration_select = "input_select.ai_kuca_duration_select"
        self.version = "V1." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")

        # Logging and status
        self.log_level = "INFO"
        self.log_sensor_entity = "sensor.ai_kuca_log"
        self.log_history_seconds = 120
        self.log_max_items = 50
        system_cfg = self.load_system_config()
        self.log_level = system_cfg.get("logging_level", self.log_level)
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get("config", log_cfg.get("sensor_entity", self.log_sensor_entity))
        self.log_history_seconds = int(log_cfg.get("history_seconds", self.log_history_seconds))
        self.log_max_items = int(log_cfg.get("max_items", self.log_max_items))
        self.status_sensor = log_map.get("config_status", "sensor.ai_kuca_config")

        # === AUTOMATSKO POPUNJAVANJE SVIH input_select entiteta ===
        all_entities = list(self.get_state().keys())
        # Dohvati sve input_select entitete iz HA
        input_selects = [e for e in all_entities if e.startswith("input_select.")]

        # Mapiraj logiku za automatsko popunjavanje prema nazivu entiteta
        for dropdown in input_selects:
            name = dropdown.split(".",1)[1]
            # Preskoči boost_select, duration_select i ai_kuca_config_mode jer se pune posebno ili imaju statičke opcije
            if name in ["ai_kuca_boost_select", "ai_kuca_duration_select", "ai_kuca_config_mode"]:
                continue
            # Prilagodi filtere prema tipu dropdowna
            if "flow_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and "flow" in e]
            elif "boiler_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and "boiler" in e]
            elif "outdoor_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and ("outdoor" in e or "vanjski" in e)]
            elif "climate" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("climate.")]
            elif "temp_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and "temp" in e]
            elif "humidity_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and "humidity" in e]
            elif "fan" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("fan.")]
            elif "switch" in name or "valve" in name or "pump" in name or "active" in name or "eco" in name or "overheat" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("switch.") or e.startswith("input_boolean.")]
            elif "room_select" in name:
                # Pretpostavi da su sobe definirane kao zone ili grupe
                options = ["NONE"] + [e for e in all_entities if e.startswith("zone.") or e.startswith("group.")]
            elif "target_sensor" in name:
                options = ["NONE"] + [e for e in all_entities if e.startswith("sensor.") and "target" in e]
            elif "boost" in name or "duration" in name:
                # Ove ostavi s default opcijama
                options = ["NONE", "<izaberi>"]
            else:
                # Za sve ostale, ostavi default opcije
                options = ["NONE", "<izaberi>"]
            self.call_service(
                "input_select/set_options",
                entity_id=dropdown,
                options=options
            )
        self.ai_kuca_heating_eco_switch = "input_select.ai_kuca_heating_eco_switch"
        self.ai_kuca_heating_overheat_switch = "input_select.ai_kuca_heating_overheat_switch"
        self.ai_kuca_pump_switch = "input_select.ai_kuca_pump_switch"
        self.ai_kuca_valve_pause = "input_select.ai_kuca_valve_pause"
        self.ai_kuca_valve_open = "input_select.ai_kuca_valve_open"
        self.ai_kuca_valve_close = "input_select.ai_kuca_valve_close"
        self.ai_kuca_flow_sensor_2 = "input_select.ai_kuca_flow_sensor_2"
        self.ai_kuca_target_sensor = "input_select.ai_kuca_target_sensor"
        self.ai_kuca_room_builder_climate = "input_select.ai_kuca_room_builder_climate"
        self.ai_kuca_room_builder_temp_sensor = "input_select.ai_kuca_room_builder_temp_sensor"
        self.ai_kuca_room_builder_humidity_sensor = "input_select.ai_kuca_room_builder_humidity_sensor"
        self.ai_kuca_room_builder_fan = "input_select.ai_kuca_room_builder_fan"
        self.boost_soba = "input_select.boost_soba"
        self.turbo_boost_duration = "input_select.turbo_boost_duration"
        self.ai_kuca_boost_select = "input_select.ai_kuca_boost_select"
        self.ai_kuca_duration_select = "input_select.ai_kuca_duration_select"

        # input_number (samo reference, za popunjavanje vrijednosti ili validaciju)
        self.input_numbers = [
            "input_number.ai_kuca_param_max_room_temp",
            "input_number.ai_kuca_param_min_room_temp",
            "input_number.ai_kuca_param_eco_delta",
            "input_number.ai_kuca_param_overheat_loop_interval",
            "input_number.ai_kuca_param_stage1_on",
            "input_number.ai_kuca_param_stage1_off",
            "input_number.ai_kuca_param_stage2_on",
            "input_number.ai_kuca_param_stage2_off",
            "input_number.ai_kuca_param_valve_start_delay",
            "input_number.ai_kuca_param_valve_deadband",
            "input_number.ai_kuca_param_valve_min_pulse",
            "input_number.ai_kuca_param_valve_max_pulse",
            "input_number.ai_kuca_param_valve_max_error",
            "input_number.ai_kuca_param_pump_start_delay",
            "input_number.ai_kuca_param_pump_off_delay",
            "input_number.ai_kuca_param_pump_cooldown",
            "input_number.ai_kuca_param_pump_min_on",
            "input_number.ai_kuca_param_pump_min_off",
            "input_number.ai_kuca_param_pump_loop_interval",
            "input_number.ai_kuca_param_pred_window_short",
            "input_number.ai_kuca_param_pred_window_long",
            "input_number.ai_kuca_param_pred_min_points_short",
            "input_number.ai_kuca_param_pred_min_points_long",
            "input_number.ai_kuca_param_pred_loss_coeff",
            "input_number.ai_kuca_param_pred_window_mult",
            "input_number.ai_kuca_param_pred_weight_short",
            "input_number.ai_kuca_param_pred_weight_long",
            "input_number.ai_kuca_param_vent_delta_on",
            "input_number.ai_kuca_param_vent_delta_off",
            "input_number.ai_kuca_param_vent_abs_on",
            "input_number.ai_kuca_param_vent_abs_off",
            "input_number.ai_kuca_param_vent_min_on_sec",
            "input_number.ai_kuca_param_vent_min_off_sec",
            "input_number.ai_kuca_param_vent_outdoor_max",
            "input_number.ai_kuca_param_vent_interval",
            "input_number.ai_kuca_param_flow_base_offset",
            "input_number.ai_kuca_param_flow_t_ref",
            "input_number.ai_kuca_param_flow_slope_cold",
            "input_number.ai_kuca_param_flow_slope_mid",
            "input_number.ai_kuca_param_flow_slope_warm",
            "input_number.ai_kuca_param_flow_min_temp",
            "input_number.ai_kuca_param_flow_max_temp",
            "input_number.ai_kuca_param_flow_boiler_hyst_on",
            "input_number.ai_kuca_param_flow_boiler_hyst_off",
            "input_number.ai_kuca_param_flow_boiler_offset",
        ]

        # Backwards compatibility for old code
        self.system_config_input = self.ai_kuca_system_config
        self.room_config_input = self.ai_kuca_room_config
        self.reload_toggle = self.ai_kuca_reload_config
        self.config_mode = self.ai_kuca_config_mode
        self.room_select = self.ai_kuca_room_select
        self.select_flow_sensor = self.ai_kuca_heating_flow_sensor
        self.select_boiler_sensor = self.ai_kuca_heating_boiler_sensor
        self.select_outdoor_sensor = self.ai_kuca_heating_outdoor_sensor
        self.select_active_switch = self.ai_kuca_heating_active_switch
        self.select_eco_switch = self.ai_kuca_heating_eco_switch
        self.select_overheat_switch = self.ai_kuca_heating_overheat_switch
        self.select_pump_switch = self.ai_kuca_pump_switch
        self.select_valve_pause = self.ai_kuca_valve_pause
        self.select_valve_open = self.ai_kuca_valve_open
        self.select_valve_close = self.ai_kuca_valve_close
        self.select_flow_sensor_2 = self.ai_kuca_flow_sensor_2
        self.select_target_sensor = self.ai_kuca_target_sensor
        self.outdoor_temp_sensors_text = self.ai_kuca_outdoor_temp_sensors
        self.build_config_toggle = self.ai_kuca_generate_config
        self.room_builder_name = self.ai_kuca_room_builder_name
        self.room_builder_target = self.ai_kuca_room_builder_target
        self.room_builder_window_sensors = self.ai_kuca_room_builder_windows
        self.room_builder_climate = self.ai_kuca_room_builder_climate
        self.room_builder_temp_sensor = self.ai_kuca_room_builder_temp_sensor
        self.room_builder_humidity_sensor = self.ai_kuca_room_builder_humidity_sensor
        self.room_builder_fan = self.ai_kuca_room_builder_fan
        self.room_builder_generate = self.ai_kuca_room_builder_generate
        self.room_builder_delete = self.ai_kuca_room_builder_delete

        # ...existing code...
        self.param_max_room_temp = "input_number.ai_kuca_param_max_room_temp"
        self.param_min_room_temp = "input_number.ai_kuca_param_min_room_temp"
        self.param_eco_delta = "input_number.ai_kuca_param_eco_delta"

        # Overheat
        self.param_overheat_loop_interval = "input_number.ai_kuca_param_overheat_loop_interval"
        self.param_stage1_on = "input_number.ai_kuca_param_stage1_on"
        self.param_stage1_off = "input_number.ai_kuca_param_stage1_off"
        self.param_stage2_on = "input_number.ai_kuca_param_stage2_on"
        self.param_stage2_off = "input_number.ai_kuca_param_stage2_off"

        # Valve Control
        self.param_valve_start_delay = "input_number.ai_kuca_param_valve_start_delay"
        self.param_valve_deadband = "input_number.ai_kuca_param_valve_deadband"
        self.param_valve_min_pulse = "input_number.ai_kuca_param_valve_min_pulse"
        self.param_valve_max_pulse = "input_number.ai_kuca_param_valve_max_pulse"
        self.param_valve_max_error = "input_number.ai_kuca_param_valve_max_error"
        self.param_pump_start_delay = "input_number.ai_kuca_param_pump_start_delay"
        self.param_pump_off_delay = "input_number.ai_kuca_param_pump_off_delay"
        self.param_pump_cooldown = "input_number.ai_kuca_param_pump_cooldown"

        # Pump
        self.param_pump_min_on = "input_number.ai_kuca_param_pump_min_on"
        self.param_pump_min_off = "input_number.ai_kuca_param_pump_min_off"
        self.param_pump_loop_interval = "input_number.ai_kuca_param_pump_loop_interval"

        # Predictive
        self.param_pred_window_short = "input_number.ai_kuca_param_pred_window_short"
        self.param_pred_window_long = "input_number.ai_kuca_param_pred_window_long"
        self.param_pred_min_points_short = "input_number.ai_kuca_param_pred_min_points_short"
        self.param_pred_min_points_long = "input_number.ai_kuca_param_pred_min_points_long"
        self.param_pred_loss_coeff = "input_number.ai_kuca_param_pred_loss_coeff"
        self.param_pred_window_mult = "input_number.ai_kuca_param_pred_window_mult"
        self.param_pred_weight_short = "input_number.ai_kuca_param_pred_weight_short"
        self.param_pred_weight_long = "input_number.ai_kuca_param_pred_weight_long"

        # Ventilation
        self.param_vent_delta_on = "input_number.ai_kuca_param_vent_delta_on"
        self.param_vent_delta_off = "input_number.ai_kuca_param_vent_delta_off"
        self.param_vent_abs_on = "input_number.ai_kuca_param_vent_abs_on"
        self.param_vent_abs_off = "input_number.ai_kuca_param_vent_abs_off"
        self.param_vent_min_on_sec = "input_number.ai_kuca_param_vent_min_on_sec"
        self.param_vent_min_off_sec = "input_number.ai_kuca_param_vent_min_off_sec"
        self.param_vent_outdoor_max = "input_number.ai_kuca_param_vent_outdoor_max"
        self.param_vent_interval = "input_number.ai_kuca_param_vent_interval"


        self.listen_state(self._on_config_text_changed, self.system_config_input)
        self.listen_state(self._on_config_text_changed, self.room_config_input)
        self.listen_state(self._on_reload_toggle, self.reload_toggle)
        self.listen_state(self._on_build_config, self.build_config_toggle)
        self.listen_state(self._on_build_room_config, self.room_builder_generate)
        self.listen_state(self._on_delete_room, self.room_builder_delete)
        self.listen_state(self._on_config_mode_changed, self.config_mode)
        self.listen_state(self._on_room_selected, self.room_select)

        self.run_in(self._ensure_ui_helpers, 1)

        self.log(f"[CONFIG] AI Config Validator {self.version} pokrenut")

        # PrikaĹľi trenutne postavke u UI
        self.run_in(self._show_current_config, 1)
        
        # Popuni sve dropdown-ove sa dostupnim entitetima na startup
        self.run_in(self._populate_all_dropdowns, 2)
        
        # UÄŤitaj vrijednosti iz system_configs.yaml na startup
        self.run_in(self._load_system_config_values, 3)
        
        # Populiraj dropdown opcije sa dostupnim entitetima iz HA
        self.run_in(self._update_ui_select_options, 3)

        # Run check after all initialization is complete (now safe to call check_config)
        config_check_interval = int(system_cfg.get("config_validator_interval", 300))
        self.run_in(self.check_config, 2)  # 2 seconds after all init complete
        self.run_every(self.check_config, "now", config_check_interval)

    def check_config(self, kwargs):
        system_cfg = self.load_system_config()
        missing = []

        if not isinstance(system_cfg, dict) or not system_cfg:
            missing.append("system_configs.yaml (ne moze se ucitati ili je prazna)")
            self._report(missing)
            return

        def require(path, value):
            if value in (None, "", [], {}):
                missing.append(path)

        # ------- heating_main -------
        heating = system_cfg.get("heating_main", {}) or {}
        require("heating_main.active_switch", heating.get("active_switch"))
        require("heating_main.eco_switch", heating.get("eco_switch"))
        require("heating_main.overheat_switch", heating.get("overheat_switch"))
        require("heating_main.flow_sensor", heating.get("flow_sensor"))
        require("heating_main.boiler_sensor", heating.get("boiler_sensor"))
        require("heating_main.outdoor_sensor", heating.get("outdoor_sensor"))

        # ------- overheat -------
        overheat = system_cfg.get("overheat", {}) or {}
        require("overheat.overheat_switch", overheat.get("overheat_switch"))
        require("overheat.valve_pause", overheat.get("valve_pause"))
        require("overheat.valve_open", overheat.get("valve_open"))
        require("overheat.stage1_on", overheat.get("stage1_on"))
        require("overheat.stage1_off", overheat.get("stage1_off"))
        require("overheat.stage2_on", overheat.get("stage2_on"))
        require("overheat.stage2_off", overheat.get("stage2_off"))

        # ------- valve_control -------
        valve = system_cfg.get("valve_control", {}) or {}
        require("valve_control.flow_sensor", valve.get("flow_sensor"))
        require("valve_control.flow_sensor_2", valve.get("flow_sensor_2"))
        require("valve_control.target_sensor", valve.get("target_sensor"))
        require("valve_control.valve_open", valve.get("valve_open"))
        require("valve_control.valve_close", valve.get("valve_close"))
        require("valve_control.pump_switch", valve.get("pump_switch"))
        require("valve_control.valve_pause", valve.get("valve_pause"))
        require("valve_control.boiler_sensor", valve.get("boiler_sensor"))
        require("valve_control.outdoor_sensor", valve.get("outdoor_sensor"))

        # ------- pump -------
        pump = system_cfg.get("pump", {}) or {}
        require("pump.pump_switch", pump.get("pump_switch"))
        require("pump.overheat_switch", pump.get("overheat_switch"))
        require("pump.min_on_seconds", pump.get("min_on_seconds"))
        require("pump.min_off_seconds", pump.get("min_off_seconds"))

        # ------- boost -------
        boost = system_cfg.get("boost", {}) or {}
        require("boost.boost_select", boost.get("boost_select"))
        require("boost.duration_select", boost.get("duration_select"))
        require("boost.duration_options", boost.get("duration_options"))
        require("boost.flow_target", boost.get("flow_target"))
        require("boost.flow_target_input", boost.get("flow_target_input"))

        # ------- predictive -------
        predictive = system_cfg.get("predictive", {}) or {}
        require("predictive.forecast_entity", predictive.get("forecast_entity"))
        require("predictive.pump_switch", predictive.get("pump_switch"))

        # ------- ventilation -------
        ventilation = system_cfg.get("ventilation", {}) or {}
        require("ventilation.outdoor_humidity_sensor", ventilation.get("outdoor_humidity_sensor"))

        # ------- status -------
        status = system_cfg.get("ai_kuca_status", {}) or {}
        require("ai_kuca_status.app_names", status.get("app_names"))

        # Room configs should exist and contain at least one room.
        room_cfg = self.load_yaml_file("room_configs.yaml")
        if not isinstance(room_cfg, dict) or not room_cfg:
            missing.append("room_configs.yaml (prazna ili ne postoji)")

        self._report(missing)

    def _report(self, missing):
        now = time.time()
        now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        if missing:
            msg = "CONFIG ERROR: nedostaju konfiguracije: " + ", ".join(missing)
            self.log(msg, level="ERROR")
            self.set_state(
                self.status_sensor,
                state="ERROR",
                attributes={
                    "missing": missing,
                    "checked_at": now_iso,
                },
            )
        else:
            msg = "CONFIG OK"
            self.log(msg, level="INFO")
            self.set_state(
                self.status_sensor,
                state="OK",
                attributes={
                    "checked_at": now_iso,
                },
            )

    def load_system_config(self):
        return self.load_yaml_file("system_configs.yaml")

    def load_yaml_file(self, filename):
        """Load YAML config from disk, optionally overridden by HA input_text."""
        # Prefer a UI-edited copy stored in an input_text entity.
        entity_name = f"input_text.ai_kuca_{os.path.splitext(filename)[0]}"
        ui_text = self.get_state(entity_name)
        if isinstance(ui_text, str) and ui_text.strip():
            try:
                return yaml.safe_load(ui_text) or {}
            except Exception as ex:
                self.log(
                    f"[CONFIG] Config parse error from {entity_name}: {ex}",
                    level="ERROR",
                )
                # Fall back to disk file below.

        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", filename)
        )
        if not os.path.exists(path):
            self.log(f"[CONFIG] Config file missing: {path}", level="ERROR")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Sync disk file back into HA UI (so user can edit it there)
            if isinstance(ui_text, str) and ui_text.strip() == "":
                self.set_state(entity_name, state=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))

            return data
        except Exception as ex:
            self.log(f"[CONFIG] Config file parse error: {path} -> {ex}", level="ERROR")
            return {}

    def _save_yaml_file(self, filename, data):
        """Save YAML data to disk file."""
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", filename)
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
            self.log(f"[CONFIG] Datoteka sprljena: {path}", level="INFO")
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri pisanju datoteke: {path} -> {ex}", level="ERROR")
            raise

    def _get_number_state(self, entity_id):
        """UÄŤitaj vrijednost iz input_number entiteta kao float ili None."""
        try:
            state = self.get_state(entity_id)
            if state is not None and state != "unknown":
                return float(state)
        except (ValueError, TypeError):
            pass
        return None

    def _on_config_text_changed(self, entity, attribute, old, new, kwargs):
        """Handler when a config input_text value changes in Home Assistant."""
        if not isinstance(new, str):
            return

        # If HA users edit config text, we keep it as the source of truth until they
        # explicitly request a reload/write via the reload toggle.
        self.log(f"Config text updated in {entity}", level="DEBUG")

    def _on_reload_toggle(self, entity, attribute, old, new, kwargs):
        """Handler when the reload boolean is toggled in Home Assistant."""
        if str(new).lower() != "on":
            return

        self.log("Reload toggle activated: writing UI config to disk", level="INFO")

        success = True
        for filename, input_entity in [
            ("system_configs.yaml", self.system_config_input),
            ("room_configs.yaml", self.room_config_input),
        ]:
            ui_text = self.get_state(input_entity) or ""
            if not ui_text.strip():
                self.log(f"Skipping empty UI config for {input_entity}", level="WARNING")
                continue

            if not self._write_yaml_file(filename, ui_text):
                success = False

        # Reset the toggle so it can be used again
        self.set_state(self.reload_toggle, state="off")

        # Re-validate immediately
        self.check_config({})

        # Ask AppDaemon to reload apps so changes take effect.
        try:
            self.call_service("appdaemon/reload")
            self.log("Triggered AppDaemon reload", level="INFO")
        except Exception as ex:
            self.log(
                f"Unable to trigger AppDaemon reload: {ex}",
                level="WARNING",
            )

        if success:
            self.log("Config saved to disk successfully", level="INFO")
        else:
            self.log("Config save encountered errors", level="ERROR")

    def _write_yaml_file(self, filename, yaml_text):
        """Persist YAML text from HA UI into the local config file."""
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", filename)
        )

        try:
            data = yaml.safe_load(yaml_text) or {}
        except Exception as ex:
            self.log(
                f"Config YAML invalid for {filename}: {ex}",
                level="ERROR",
            )
            return False

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
            self.log(f"Wrote config to {path}", level="INFO")
            return True
        except Exception as ex:
            self.log(
                f"Cannot write config to {path}: {ex}",
                level="ERROR",
            )
            return False

    def _on_reload_toggle_auto(self, kwargs):
        """Automatically trigger AppDaemon reload after config changes."""
        self.log("Automatski reload aktiviran nakon sprljene konfiguracije", level="INFO")
        
        # Re-validate immediately
        self.check_config({})

        # Ask AppDaemon to reload apps so changes take effect
        try:
            self.call_service("appdaemon/reload")
            self.log("AppDaemon reload triggered successfully", level="INFO")
        except Exception as ex:
            self.log(
                f"Unable to trigger AppDaemon reload: {ex}",
                level="WARNING",
            )

    def _ensure_ui_helpers(self, kwargs=None):
        """Ensure all HA helpers from HA_helpers.yaml exist (input_text, input_boolean, input_select, input_number)."""
        helpers = []
        # input_boolean
        for entity_id in [
            self.ai_heating_active, self.ai_heating_eco, self.ai_kuca_reload_config, self.ai_kuca_generate_config,
            self.ai_kuca_room_builder_generate, self.ai_kuca_room_builder_delete
        ]:
            helpers.append({"entity_id": entity_id, "service": "input_boolean/create", "name": entity_id.split(".")[1].replace("_", " ").title()})

        # input_text
        for entity_id in [
            self.ai_kuca_system_config, self.ai_kuca_room_config, self.ai_kuca_room_builder_name, self.ai_kuca_room_builder_target,
            self.ai_kuca_room_builder_windows, self.ai_kuca_outdoor_temp_sensors, self.ai_kuca_climate_entities
        ]:
            helpers.append({"entity_id": entity_id, "service": "input_text/create", "name": entity_id.split(".")[1].replace("_", " ").title(), "initial": ""})

        # input_select
        # Prvo ai_kuca_config_mode s YAML opcijama
        helpers.append({
            "entity_id": self.ai_kuca_config_mode,
            "service": "input_select/create",
            "name": self.ai_kuca_config_mode.split(".")[1].replace("_", " ").title(),
            "options": ["-- Odaberi --", "System Config", "Room Config"]
        })
        # Ostali input_select entiteti
        for entity_id in [
            self.ai_kuca_room_select, self.ai_kuca_heating_flow_sensor, self.ai_kuca_heating_boiler_sensor,
            self.ai_kuca_heating_outdoor_sensor, self.ai_kuca_heating_active_switch, self.ai_kuca_heating_eco_switch,
            self.ai_kuca_heating_overheat_switch, self.ai_kuca_pump_switch, self.ai_kuca_valve_pause, self.ai_kuca_valve_open,
            self.ai_kuca_valve_close, self.ai_kuca_flow_sensor_2, self.ai_kuca_target_sensor, self.ai_kuca_room_builder_climate,
            self.ai_kuca_room_builder_temp_sensor, self.ai_kuca_room_builder_humidity_sensor, self.ai_kuca_room_builder_fan,
            self.boost_soba, self.turbo_boost_duration, self.ai_kuca_boost_select, self.ai_kuca_duration_select
        ]:
            helpers.append({"entity_id": entity_id, "service": "input_select/create", "name": entity_id.split(".")[1].replace("_", " ").title(), "options": ["<izaberi>"]})

        # input_number (samo kreiranje, vrijednosti se postavljaju kroz HA UI)
        for entity_id in self.input_numbers:
            helpers.append({"entity_id": entity_id, "service": "input_number/create", "name": entity_id.split(".")[1].replace("_", " ").title()})

        for helper in helpers:
            if self.get_state(helper["entity_id"]) is not None:
                continue
            try:
                self.call_service(
                    helper["service"],
                    entity_id=helper["entity_id"],
                    name=helper.get("name"),
                    initial=helper.get("initial"),
                    options=helper.get("options"),
                )
                self.log(f"[CONFIG] Created helper {helper['entity_id']} via {helper['service']}", level="DEBUG")
            except Exception as ex:
                self.log(f"[CONFIG] Unable to create helper {helper['entity_id']}: {ex}", level="WARNING")

    def _show_current_config(self, kwargs):
        """Load and display current config summary from disk."""
        try:
            system_cfg = self.load_yaml_file("system_configs.yaml") or {}
            room_cfg = self.load_yaml_file("room_configs.yaml") or {}
            
            # PrikaĹľi broj soba kao summary
            rooms = list(room_cfg.keys()) if room_cfg else []
            summary_text = f"UÄŤitane sobe: {', '.join(rooms) if rooms else 'nema soba'}"

            # PrikaĹľi status
            system_status = "System config: OK" if system_cfg else "System config: EMPTY"
            self.log(f"[CONFIG] {system_status} | {summary_text}", level="INFO")
            
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri uÄŤitavanju config datoteka: {ex}", level="WARNING")

    def _update_ui_select_options(self, kwargs):
        """Populate dropdown helper options from current HA entity registry."""
        entities = self.get_state() or {}

        sensors = sorted([e for e in entities.keys() if e.startswith("sensor.")])
        switches = sorted([e for e in entities.keys() if e.startswith("switch.")])
        input_bools = sorted([e for e in entities.keys() if e.startswith("input_boolean.")])

        select_mapping = {
            self.select_flow_sensor: sensors,
            self.select_boiler_sensor: sensors,
            self.select_active_switch: input_bools,
            self.select_eco_switch: input_bools,
            self.select_overheat_switch: input_bools,
            self.select_pump_switch: switches,
            self.room_builder_climate: [e for e in entities.keys() if e.startswith("climate.")],
            self.room_builder_temp_sensor: sensors,
            self.room_builder_humidity_sensor: sensors,
            self.room_builder_fan: [e for e in entities.keys() if e.startswith("fan.")],
        }

        for entity_id, options in select_mapping.items():
            if self.get_state(entity_id) is None:
                continue
            try:
                self.call_service(
                    "input_select/set_options",
                    entity_id=entity_id,
                    options=options,
                )
            except Exception as ex:
                self.log(
                    f"[CONFIG] Unable to update options for {entity_id}: {ex}",
                    level="WARNING",
                )

    def _on_build_config(self, entity, attribute, old, new, kwargs):
        """Build system_configs.yaml content from selected dropdown values and ALL numeric parameters."""
        if str(new).lower() != "on":
            return

        self.log("Building config from dropdown selectors and numeric parameters", level="INFO")
        is_entity = lambda v: isinstance(v, str) and "." in v and v != "NONE"

        system_cfg = self.load_system_config() or {}

        # ================ HEATING MAIN ================
        heating = system_cfg.get("heating_main", {}) or {}
        
        # Entity selectors
        selected_entities = {
            "active_switch": self.get_state(self.select_active_switch),
            "eco_switch": self.get_state(self.select_eco_switch),
            "overheat_switch": self.get_state(self.select_overheat_switch),
            "flow_sensor": self.get_state(self.select_flow_sensor),
            "boiler_sensor": self.get_state(self.select_boiler_sensor),
            "outdoor_sensor": self.get_state(self.select_outdoor_sensor),
        }
        for k, v in selected_entities.items():
            if isinstance(v, str) and "." in v:
                heating[k] = v
        
        # Numeric parameters for heating_main
        max_temp = self._get_number_state(self.param_max_room_temp)
        if max_temp is not None:
            heating["max_room_temp"] = max_temp
        
        min_temp = self._get_number_state(self.param_min_room_temp)
        if min_temp is not None:
            heating["min_room_temp"] = min_temp
        
        eco_delta = self._get_number_state(self.param_eco_delta)
        if eco_delta is not None:
            heating["eco_delta"] = eco_delta
        
        system_cfg["heating_main"] = heating

        # ================ OVERHEAT ================
        overheat = system_cfg.get("overheat", {}) or {}
        
        # Entity selectors
        if is_entity(self.get_state(self.select_overheat_switch)):
            overheat["overheat_switch"] = self.get_state(self.select_overheat_switch)
        if is_entity(self.get_state(self.select_valve_pause)):
            overheat["valve_pause"] = self.get_state(self.select_valve_pause)
        if is_entity(self.get_state(self.select_valve_open)):
            overheat["valve_open"] = self.get_state(self.select_valve_open)
        
        # Numeric parameters
        loop_int = self._get_number_state(self.param_overheat_loop_interval)
        if loop_int is not None:
            overheat["main_loop_interval"] = int(loop_int)
        
        s1_on = self._get_number_state(self.param_stage1_on)
        if s1_on is not None:
            overheat["stage1_on"] = s1_on
        
        s1_off = self._get_number_state(self.param_stage1_off)
        if s1_off is not None:
            overheat["stage1_off"] = s1_off
        
        s2_on = self._get_number_state(self.param_stage2_on)
        if s2_on is not None:
            overheat["stage2_on"] = s2_on
        
        s2_off = self._get_number_state(self.param_stage2_off)
        if s2_off is not None:
            overheat["stage2_off"] = s2_off
        
        system_cfg["overheat"] = overheat

        # ================ VALVE CONTROL ================
        valve_control = system_cfg.get("valve_control", {}) or {}
        
        # Entity selectors
        if is_entity(self.get_state(self.select_valve_pause)):
            valve_control["valve_pause"] = self.get_state(self.select_valve_pause)
        if is_entity(self.get_state(self.select_valve_open)):
            valve_control["valve_open"] = self.get_state(self.select_valve_open)
        if is_entity(self.get_state(self.select_valve_close)):
            valve_control["valve_close"] = self.get_state(self.select_valve_close)
        if is_entity(self.get_state(self.select_flow_sensor_2)):
            valve_control["flow_sensor_2"] = self.get_state(self.select_flow_sensor_2)
        if is_entity(self.get_state(self.select_target_sensor)):
            valve_control["target_sensor"] = self.get_state(self.select_target_sensor)
        
        # Numeric parameters
        start_del = self._get_number_state(self.param_valve_start_delay)
        if start_del is not None:
            valve_control["start_delay"] = start_del
        
        deadband = self._get_number_state(self.param_valve_deadband)
        if deadband is not None:
            valve_control["deadband"] = deadband
        
        min_pulse = self._get_number_state(self.param_valve_min_pulse)
        if min_pulse is not None:
            valve_control["min_base_pulse"] = min_pulse
        
        max_pulse = self._get_number_state(self.param_valve_max_pulse)
        if max_pulse is not None:
            valve_control["max_base_pulse"] = max_pulse
        
        max_err = self._get_number_state(self.param_valve_max_error)
        if max_err is not None:
            valve_control["max_error"] = max_err
        
        pump_start = self._get_number_state(self.param_pump_start_delay)
        if pump_start is not None:
            valve_control["pump_start_delay"] = int(pump_start)
        
        pump_off = self._get_number_state(self.param_pump_off_delay)
        if pump_off is not None:
            valve_control["pump_off_delay"] = int(pump_off)
        
        cooldown = self._get_number_state(self.param_pump_cooldown)
        if cooldown is not None:
            valve_control["cooldown_after_pulse"] = int(cooldown)
        
        system_cfg["valve_control"] = valve_control

        # ================ PUMP ================
        pump = system_cfg.get("pump", {}) or {}
        
        pump_switch = self.get_state(self.select_pump_switch)
        if isinstance(pump_switch, str) and "." in pump_switch:
            pump["pump_switch"] = pump_switch
        
        # Numeric parameters
        pump_min_on = self._get_number_state(self.param_pump_min_on)
        if pump_min_on is not None:
            pump["min_on_seconds"] = int(pump_min_on)
        
        pump_min_off = self._get_number_state(self.param_pump_min_off)
        if pump_min_off is not None:
            pump["min_off_seconds"] = int(pump_min_off)
        
        pump_loop = self._get_number_state(self.param_pump_loop_interval)
        if pump_loop is not None:
            pump["main_loop_interval"] = int(pump_loop)
        
        system_cfg["pump"] = pump

        # ================ PREDICTIVE ================
        predictive = system_cfg.get("predictive", {}) or {}
        
        # Numeric parameters
        win_short = self._get_number_state(self.param_pred_window_short)
        if win_short is not None:
            predictive["window_short_minutes"] = int(win_short)
        
        win_long = self._get_number_state(self.param_pred_window_long)
        if win_long is not None:
            predictive["window_long_minutes"] = int(win_long)
        
        pts_short = self._get_number_state(self.param_pred_min_points_short)
        if pts_short is not None:
            predictive["min_points_short"] = int(pts_short)
        
        pts_long = self._get_number_state(self.param_pred_min_points_long)
        if pts_long is not None:
            predictive["min_points_long"] = int(pts_long)
        
        loss_coeff = self._get_number_state(self.param_pred_loss_coeff)
        if loss_coeff is not None:
            predictive["loss_coeff_default"] = float(loss_coeff)
        
        win_mult = self._get_number_state(self.param_pred_window_mult)
        if win_mult is not None:
            predictive["window_loss_multiplier"] = win_mult
        
        w_short = self._get_number_state(self.param_pred_weight_short)
        if w_short is not None:
            predictive["weight_short"] = w_short
        
        w_long = self._get_number_state(self.param_pred_weight_long)
        if w_long is not None:
            predictive["weight_long"] = w_long
        
        system_cfg["predictive"] = predictive

        # ================ VENTILATION ================
        ventilation = system_cfg.get("ventilation", {}) or {}
        
        # Numeric parameters
        vent_d_on = self._get_number_state(self.param_vent_delta_on)
        if vent_d_on is not None:
            ventilation["delta_on"] = vent_d_on
        
        vent_d_off = self._get_number_state(self.param_vent_delta_off)
        if vent_d_off is not None:
            ventilation["delta_off"] = vent_d_off
        
        vent_abs_on = self._get_number_state(self.param_vent_abs_on)
        if vent_abs_on is not None:
            ventilation["abs_on"] = vent_abs_on
        
        vent_abs_off = self._get_number_state(self.param_vent_abs_off)
        if vent_abs_off is not None:
            ventilation["abs_off"] = vent_abs_off
        
        vent_min_on = self._get_number_state(self.param_vent_min_on_sec)
        if vent_min_on is not None:
            ventilation["min_on_sec"] = int(vent_min_on)
        
        vent_min_off = self._get_number_state(self.param_vent_min_off_sec)
        if vent_min_off is not None:
            ventilation["min_off_sec"] = int(vent_min_off)
        
        vent_out_max = self._get_number_state(self.param_vent_outdoor_max)
        if vent_out_max is not None:
            ventilation["outdoor_humidity_max"] = vent_out_max
        
        vent_int = self._get_number_state(self.param_vent_interval)
        if vent_int is not None:
            ventilation["interval_sec"] = int(vent_int)
        
        system_cfg["ventilation"] = ventilation

        # PiĹˇi direktno u system_configs.yaml na disk
        try:
            self._save_yaml_file("system_configs.yaml", system_cfg)
            self.log("[CONFIG] Konfiguracija sa svim parametrima uspjeĹˇno spremljena u system_configs.yaml", level="INFO")
            # Triggeraj reload automatski nakon spremanja
            self.run_in(self._on_reload_toggle_auto, 1)
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri pisanju konfiguracije: {ex}", level="ERROR")

        # Reset the button so it can be used again.
        self.set_state(self.build_config_toggle, state="off")

    def _on_build_room_config(self, entity, attribute, old, new, kwargs):
        """Build a room entry in room_configs.yaml from selected dropdown values."""
        if str(new).lower() != "on":
            return

        room_name = (self.get_state(self.room_builder_name) or "").strip()
        if not room_name:
            self.log("Room builder: ime sobe nije uneseno", level="WARNING")
            self.set_state(self.room_builder_generate, state="off")
            return

        self.log(f"Building room config for '{room_name}'", level="INFO")

        room_cfg = self.load_yaml_file("room_configs.yaml") or {}
        room_cfg.setdefault(room_name, {})

        climate = self.get_state(self.room_builder_climate) or ""
        if isinstance(climate, str) and "." in climate:
            room_cfg[room_name]["climate"] = climate

        temp_sensor = self.get_state(self.room_builder_temp_sensor) or ""
        if isinstance(temp_sensor, str) and "." in temp_sensor:
            room_cfg[room_name]["temp_sensor"] = temp_sensor

        humidity_sensor = self.get_state(self.room_builder_humidity_sensor) or ""
        if isinstance(humidity_sensor, str) and "." in humidity_sensor:
            room_cfg[room_name]["humidity_sensor"] = humidity_sensor

        fan = self.get_state(self.room_builder_fan) or ""
        if isinstance(fan, str) and "." in fan:
            room_cfg[room_name]["fan"] = fan

        target = (self.get_state(self.room_builder_target) or "").strip()
        if target:
            try:
                room_cfg[room_name]["target"] = float(target)
            except Exception:
                room_cfg[room_name]["target"] = target

        windows = (self.get_state(self.room_builder_window_sensors) or "").strip()
        if windows:
            room_cfg[room_name]["window_sensors"] = [
                w.strip() for w in windows.split(",") if w.strip()
            ]

        # PiĹˇi direktno u room_configs.yaml na disk
        try:
            self._save_yaml_file("room_configs.yaml", room_cfg)
            self.log(f"[CONFIG] Soba '{room_name}' dodana u room_configs.yaml", level="INFO")
            # Triggeraj reload automatski nakon spremanja
            self.run_in(self._on_reload_toggle_auto, 1)
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri pisanju room config: {ex}", level="ERROR")

        # Reset the button so it can be used again.
        self.set_state(self.room_builder_generate, state="off")

    def _on_delete_room(self, entity, attribute, old, new, kwargs):
        """BriĹˇi sobu iz room_configs.yaml."""
        if str(new).lower() != "on":
            return

        room_to_delete = (self.get_state(self.room_select) or "").strip()
        if not room_to_delete or room_to_delete.lower() == "none":
            self.log("Delete room: nije odabrana soba", level="WARNING")
            self.set_state(self.room_builder_delete, state="off")
            return

        self.log(f"Brisanje sobe '{room_to_delete}'", level="INFO")

        room_cfg = self.load_yaml_file("room_configs.yaml") or {}
        if room_to_delete in room_cfg:
            del room_cfg[room_to_delete]
            try:
                self._save_yaml_file("room_configs.yaml", room_cfg)
                self.log(f"[CONFIG] Soba '{room_to_delete}' obrisana iz room_configs.yaml", level="INFO")
                # Triggeraj reload automatski nakon brisanja
                self.run_in(self._on_reload_toggle_auto, 1)
                # Resetuj sve poljenavigiramo
                self.set_state(self.room_select, state="NONE")
                self.set_state(self.room_builder_name, state="")
                self.set_state(self.room_builder_target, state="")
                self.set_state(self.room_builder_climate, state="NONE")
                self.set_state(self.room_builder_temp_sensor, state="NONE")
                self.set_state(self.room_builder_humidity_sensor, state="NONE")
                self.set_state(self.room_builder_fan, state="NONE")
                self.set_state(self.room_builder_window_sensors, state="")
            except Exception as ex:
                self.log(f"[CONFIG] GreĹˇka pri brisanju sobe: {ex}", level="ERROR")
        else:
            self.log(f"Soba '{room_to_delete}' nije pronaÄ‘ena u konfiguraciji", level="WARNING")

        # Reset the delete button so it can be used again.
        self.set_state(self.room_builder_delete, state="off")

    def _on_config_mode_changed(self, entity, attribute, old, new, kwargs):
        """Handler kada se promijeni config_mode dropdown (System Config / Room Config)."""
        mode = (str(new) or "").strip().lower()
        
        self.log(f"[CONFIG] config_mode promijenjeno: mode='{mode}' (raw='{new}')", level="INFO")
        
        if mode == "room config":
            self.log("[CONFIG] Room Config mode odabran - uÄŤitavanje soba", level="INFO")
            # Popuni room_select sa listom dostupnih soba
            room_cfg = self.load_yaml_file("room_configs.yaml") or {}
            rooms = list(room_cfg.keys()) if room_cfg else []
            
            # Kreiraj options: NONE + sve sobe
            options = ["NONE"] + sorted(rooms)
            
            try:
                self.call_service(
                    "input_select/set_options",
                    entity_id=self.room_select,
                    options=options,
                )
                self.log(f"[CONFIG] Popunjene dostupne sobe: {rooms}", level="INFO")
            except Exception as ex:
                self.log(f"[CONFIG] GreĹˇka pri popunjavanju room_select: {ex}", level="WARNING")
        
        elif mode == "system config":
            self.log("[CONFIG] System Config mode odabran - uÄŤitavanje vrijednosti", level="INFO")
            # Resetaj room_select na NONE
            self.set_state(self.room_select, state="NONE")
            
            # UÄŤitaj sve dostupne entitete iz HA sa zakaĹˇnjenjem
            self.run_in(self._populate_all_dropdowns, 0.1)
            
            # UÄŤitaj trenutne vrijednosti iz system_configs.yaml
            self.run_in(self._load_system_config_values, 0.2)
        else:
            self.log(f"[CONFIG] Nepoznat mode: '{mode}' - neÄ‡e se niĹˇta uÄŤitati", level="WARNING")

    def _populate_all_dropdowns(self, kwargs):
        """Popuni sve dropdown-ove sa dostupnim entitetima iz HA."""
        self.log("[CONFIG] Pokrenuta _populate_all_dropdowns()", level="INFO")
        entities = self.get_state() or {}
        
        sensors = sorted([e for e in entities.keys() if e.startswith("sensor.")])
        switches = sorted([e for e in entities.keys() if e.startswith("switch.")])
        climate = sorted([e for e in entities.keys() if e.startswith("climate.")])
        fans = sorted([e for e in entities.keys() if e.startswith("fan.")])
        input_bools = sorted([e for e in entities.keys() if e.startswith("input_boolean.")])
        
        self.log(f"[CONFIG] PronaÄ‘eni entiteti: sensors={len(sensors)}, switches={len(switches)}, climate={len(climate)}, fans={len(fans)}, input_bools={len(input_bools)}", level="INFO")
        
        # Options za svaki dropdown (NONE + dostupni entiteti)
        options_map = {
            self.select_flow_sensor: ["NONE"] + sensors,
            self.select_boiler_sensor: ["NONE"] + sensors,
            self.select_active_switch: ["NONE"] + input_bools,
            self.select_eco_switch: ["NONE"] + input_bools,
            self.select_overheat_switch: ["NONE"] + input_bools,
            self.select_pump_switch: ["NONE"] + switches,
            self.select_valve_pause: ["NONE"] + input_bools,
            self.select_valve_open: ["NONE"] + switches,
            self.select_valve_close: ["NONE"] + switches,
            self.select_flow_sensor_2: ["NONE"] + sensors,
            self.select_target_sensor: ["NONE"] + sensors,
            self.room_builder_climate: ["NONE"] + climate,
            self.room_builder_temp_sensor: ["NONE"] + sensors,
            self.room_builder_humidity_sensor: ["NONE"] + sensors,
            self.room_builder_fan: ["NONE"] + fans,
        }
        
        for entity_id, options in options_map.items():
            try:
                self.call_service(
                    "input_select/set_options",
                    entity_id=entity_id,
                    options=options,
                )
                self.log(f"[CONFIG] Popunjeni {entity_id} sa {len(options)} opcija", level="INFO")
            except Exception as ex:
                self.log(f"[CONFIG] GreĹˇka pri popunjavanju {entity_id}: {ex}", level="WARNING")

    def _load_system_config_values(self, kwargs):
        """UÄŤitaj trenutne vrijednosti iz system_configs.yaml u dropdown-ove."""
        self.log("[CONFIG] Pokrenuta _load_system_config_values()", level="INFO")
        # Prvo popuni dostupne sobe u room_select (ÄŤak i ako je koji drugi mod aktivan)
        room_cfg = self.load_yaml_file("room_configs.yaml") or {}
        rooms = list(room_cfg.keys()) if room_cfg else []
        room_options = ["NONE"] + sorted(rooms)
        
        self.log(f"[CONFIG] Dostupne sobe: {rooms}", level="INFO")
        
        try:
            self.call_service(
                "input_select/set_options",
                entity_id=self.room_select,
                options=room_options,
            )
            self.log(f"[CONFIG] Popunjeni room_select sa {len(room_options)} opcija", level="INFO")
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri postavljanju room_select opcija: {ex}", level="WARNING")
        
        # UÄŤitaj system config vrijednosti
        system_cfg = self.load_yaml_file("system_configs.yaml") or {}
        
        heating = system_cfg.get("heating_main", {}) or {}
        pump = system_cfg.get("pump", {}) or {}
        overheat = system_cfg.get("overheat", {}) or {}
        valve_control = system_cfg.get("valve_control", {}) or {}
        
        self.log(f"[CONFIG] UÄŤitano iz system_configs.yaml: heating, pump, overheat, valve_control sekcije", level="INFO")
        
        # Postavi vrijednosti u dropdown-ove
        dropdown_map = {
            self.select_flow_sensor: heating.get("flow_sensor", "NONE"),
            self.select_boiler_sensor: heating.get("boiler_sensor", "NONE"),
            self.select_active_switch: heating.get("active_switch", "NONE"),
            self.select_eco_switch: heating.get("eco_switch", "NONE"),
            self.select_overheat_switch: heating.get("overheat_switch", "NONE"),
            self.select_pump_switch: pump.get("pump_switch", "NONE"),
            self.select_valve_pause: overheat.get("valve_pause", "NONE"),
            self.select_valve_open: overheat.get("valve_open", "NONE"),
            self.select_valve_close: valve_control.get("valve_close", "NONE"),
            self.select_flow_sensor_2: valve_control.get("flow_sensor_2", "NONE"),
            self.select_target_sensor: valve_control.get("target_sensor", "NONE"),
        }
        
        for entity_id, value in dropdown_map.items():
            try:
                if value and value != "NONE":
                    self.set_state(entity_id, state=value)
                else:
                    self.set_state(entity_id, state="NONE")
                self.log(f"[CONFIG] Postavio {entity_id} = {value}", level="INFO")
            except Exception as ex:
                self.log(f"[CONFIG] GreĹˇka pri postavljanju {entity_id}: {ex}", level="WARNING")
        
        # UÄŤitaj outdoor_temp_sensors kao comma-separated listu
        outdoor_sensors = heating.get("outdoor_temp_sensors", []) or []
        if outdoor_sensors and isinstance(outdoor_sensors, list):
            outdoor_sensors_str = ", ".join(outdoor_sensors)
            try:
                self.set_state(self.outdoor_temp_sensors_text, state=outdoor_sensors_str)
                self.log(f"[CONFIG] Postavio outdoor_temp_sensors = {outdoor_sensors_str}", level="INFO")
            except Exception as ex:
                self.log(f"[CONFIG] GreĹˇka pri postavljanju outdoor_temp_sensors: {ex}", level="WARNING")
        
        # ========== UÄŚITAJ SVE INPUT_NUMBER VRIJEDNOSTI IZ YAML ==========
        predictive = system_cfg.get("predictive", {}) or {}
        ventilation = system_cfg.get("ventilation", {}) or {}
        
        # Helper za postavljanje input_number vrijednosti
        def set_number(entity_id, value, default=None):
            if value is not None:
                try:
                    self.set_state(entity_id, state=str(value))
                except Exception as ex:
                    self.log(f"[CONFIG] GreĹˇka pri postavljanju {entity_id}: {ex}", level="WARNING")
        
        # Heating Main
        set_number(self.param_max_room_temp, heating.get("max_room_temp"))
        set_number(self.param_min_room_temp, heating.get("min_room_temp"))
        set_number(self.param_eco_delta, heating.get("eco_delta"))
        
        # Overheat
        set_number(self.param_overheat_loop_interval, overheat.get("main_loop_interval"))
        set_number(self.param_stage1_on, overheat.get("stage1_on"))
        set_number(self.param_stage1_off, overheat.get("stage1_off"))
        set_number(self.param_stage2_on, overheat.get("stage2_on"))
        set_number(self.param_stage2_off, overheat.get("stage2_off"))
        
        # Valve Control
        set_number(self.param_valve_start_delay, valve_control.get("start_delay"))
        set_number(self.param_valve_deadband, valve_control.get("deadband"))
        set_number(self.param_valve_min_pulse, valve_control.get("min_base_pulse"))
        set_number(self.param_valve_max_pulse, valve_control.get("max_base_pulse"))
        set_number(self.param_valve_max_error, valve_control.get("max_error"))
        set_number(self.param_pump_start_delay, valve_control.get("pump_start_delay"))
        set_number(self.param_pump_off_delay, valve_control.get("pump_off_delay"))
        set_number(self.param_pump_cooldown, valve_control.get("cooldown_after_pulse"))
        
        # Pump
        set_number(self.param_pump_min_on, pump.get("min_on_seconds"))
        set_number(self.param_pump_min_off, pump.get("min_off_seconds"))
        set_number(self.param_pump_loop_interval, pump.get("main_loop_interval"))
        
        # Predictive
        set_number(self.param_pred_window_short, predictive.get("window_short_minutes"))
        set_number(self.param_pred_window_long, predictive.get("window_long_minutes"))
        set_number(self.param_pred_min_points_short, predictive.get("min_points_short"))
        set_number(self.param_pred_min_points_long, predictive.get("min_points_long"))
        set_number(self.param_pred_loss_coeff, predictive.get("loss_coeff_default"))
        set_number(self.param_pred_window_mult, predictive.get("window_loss_multiplier"))
        set_number(self.param_pred_weight_short, predictive.get("weight_short"))
        set_number(self.param_pred_weight_long, predictive.get("weight_long"))
        
        # Ventilation
        set_number(self.param_vent_delta_on, ventilation.get("delta_on"))
        set_number(self.param_vent_delta_off, ventilation.get("delta_off"))
        set_number(self.param_vent_abs_on, ventilation.get("abs_on"))
        set_number(self.param_vent_abs_off, ventilation.get("abs_off"))
        set_number(self.param_vent_min_on_sec, ventilation.get("min_on_sec"))
        set_number(self.param_vent_min_off_sec, ventilation.get("min_off_sec"))
        set_number(self.param_vent_outdoor_max, ventilation.get("outdoor_humidity_max"))
        set_number(self.param_vent_interval, ventilation.get("interval_sec"))
        
        self.log("[CONFIG] UÄŤitane sve vrijednosti iz system_configs.yaml", level="INFO")

    def _on_room_selected(self, entity, attribute, old, new, kwargs):
        """Handler kada se odabere soba iz room_select dropdown."""
        room_name = (str(new) or "").strip()
        
        if room_name == "NONE" or not room_name:
            # Resetaj sva polja
            self.set_state(self.room_builder_name, state="")
            self.set_state(self.room_builder_target, state="21.0")
            self.set_state(self.room_builder_climate, state="NONE")
            self.set_state(self.room_builder_temp_sensor, state="NONE")
            self.set_state(self.room_builder_humidity_sensor, state="NONE")
            self.set_state(self.room_builder_fan, state="NONE")
            self.set_state(self.room_builder_window_sensors, state="")
            return
        
        # UÄŤitaj podatke odabrane sobe iz room_configs.yaml
        room_cfg = self.load_yaml_file("room_configs.yaml") or {}
        room_data = room_cfg.get(room_name, {})
        
        try:
            # Popuni polja sa vrijednostima sobe
            self.set_state(self.room_builder_name, state=room_name)
            
            target = room_data.get("target", "21.0")
            self.set_state(self.room_builder_target, state=str(target))
            
            climate = room_data.get("climate", "NONE")
            self.set_state(self.room_builder_climate, state=climate if climate else "NONE")
            
            temp_sensor = room_data.get("temp_sensor", "NONE")
            self.set_state(self.room_builder_temp_sensor, state=temp_sensor if temp_sensor else "NONE")
            
            humidity_sensor = room_data.get("humidity_sensor", "NONE")
            self.set_state(self.room_builder_humidity_sensor, state=humidity_sensor if humidity_sensor else "NONE")
            
            fan = room_data.get("fan", "NONE")
            self.set_state(self.room_builder_fan, state=fan if fan else "NONE")
            
            windows = room_data.get("window_sensors", [])
            windows_str = ", ".join(windows) if isinstance(windows, list) else ""
            self.set_state(self.room_builder_window_sensors, state=windows_str)
            
            self.log(f"[CONFIG] UÄŤitani podaci sobe '{room_name}'", level="INFO")
        except Exception as ex:
            self.log(f"[CONFIG] GreĹˇka pri uÄŤitavanju podataka sobe: {ex}", level="WARNING")

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)





