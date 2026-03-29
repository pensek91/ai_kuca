import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.config_loader import ConfigLoader
from ai_kuca.core.logger import push_log_to_ha
from ai_kuca.core.utils import as_float


class BaseApp(hass.Hass):
    """Shared helpers for ai_kuca apps."""

    def init_base(self):
        self.config_loader = ConfigLoader(self)

    def load_yaml_file(self, filename):
        return self.config_loader.load_yaml(filename)

    def load_system_config(self):
        return self.load_yaml_file("system_configs.yaml")

    def get_temp(self, entity):
        try:
            return as_float(self.get_state(entity), fallback=None)
        except Exception:
            return None

    def get_outdoor_temp_avg(self):
        values = []
        for ent in getattr(self, "outdoor_temp_sensors", []) or []:
            val = self.get_temp(ent)
            if val is not None:
                values.append(val)
        if not values:
            return None
        return sum(values) / len(values)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

    def log_h(self, message, level="INFO", prefix="AI_KUCA"):
        sensor = getattr(self, "log_sensor_entity", "sensor.ai_kuca_log")
        hist = int(getattr(self, "log_history_seconds", 120))
        mx = int(getattr(self, "log_max_items", 50))
        push_log_to_ha(self, message, level, sensor, hist, mx)
        if self.should_log(level):
            self.log(f"[{prefix}] {message}", level=level)
