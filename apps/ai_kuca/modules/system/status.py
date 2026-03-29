import os
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class AIKucaStatus(hass.Hass):
    """
    Klasa za provjeru statusa AI skripta.
    
    Provjerava da li su sve AI aplikacije pokrenute i rade,
    te logira greĹˇke ako neka nedostaje.
    """
    def initialize(self):
        """
        Inicijalizira AIKucaStatus skriptu.
        
        UÄŤitava listu aplikacija za provjeru i pokreÄ‡e jednokratnu
        provjeru nakon kaĹˇnjenja.
        """
        system_cfg = self.load_system_config()
        status_cfg = system_cfg.get("ai_kuca_status", {})
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})

        self.log_level = system_cfg.get("logging_level", "INFO")
        self.log_sensor_entity = log_map.get(
            "status", "sensor.ai_kuca_log_status"
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        # reset status log on start (status log should contain only OK/ERROR)
        try:
            self.set_state(
                self.log_sensor_entity,
                state="",
                attributes={"last_level": None, "last_ts": None, "history": []},
            )
        except Exception:
            pass

        self.check_delay = int(status_cfg.get("check_delay_sec", 8))
        self.app_names = status_cfg.get("app_names") or []
        if isinstance(self.app_names, str):
            self.app_names = [self.app_names]
        if not isinstance(self.app_names, list):
            self.app_names = []

        self.run_in(self.check_apps, self.check_delay)

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[STATUS] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

    def check_apps(self, kwargs):
        missing = []
        for app in self.app_names:
            try:
                obj = self.get_app(app)
            except Exception:
                obj = None
            if obj is None:
                missing.append(app)
                self.log_h(f"Provjera statusa | {app} -> NEDOSTUPNA", level="DEBUG")
            else:
                self.log_h(f"Provjera statusa | {app} -> OK", level="DEBUG")

        if missing:
            msg = f"[AI_KUCA] Upozorenje: nedostupne aplikacije: {', '.join(missing)}"
            push_log_to_ha(self, msg, "ERROR", self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
            self.log(msg, level="ERROR")
            return

        msg = "[AI_KUCA] AI_Kuca program je pokrenut bez gresaka"
        push_log_to_ha(self, msg, "WARNING", self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        self.log(msg, level="WARNING")

    def load_system_config(self):
        return self.load_yaml_file("system_configs.yaml")

    def load_yaml_file(self, filename):
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", filename)
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}


