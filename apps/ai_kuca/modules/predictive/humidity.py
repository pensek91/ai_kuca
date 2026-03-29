import os
import time
import json
from datetime import datetime, timezone
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class PredictiveHumidity(hass.Hass):
    """
    Klasa za prediktivne senzore vlage soba.
    
    RaÄŤuna trend vlage na temelju povijesti i objavljuje senzore
    za predviÄ‘enu vlagu za 15min, 30min i 1h.
    """
    def initialize(self):
        """
        Inicijalizira PredictiveHumidity skriptu.
        
        UÄŤitava konfiguraciju soba i postavke povijesti,
        te pokreÄ‡e petlju aĹľuriranja svakih interval_sec sekundi.
        """
        self.version = "V1." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")

        config_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "room_configs.yaml")
        )
        with open(config_path, "r", encoding="utf-8") as f:
            self.rooms = yaml.safe_load(f) or {}

        system_cfg = self.load_system_config()
        cfg = system_cfg.get("predictive_humidity", {})

        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "predictive_humidity", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        # osiguraj da log senzor postoji u HA
        try:
            self.set_state(
                self.log_sensor_entity,
                state="",
                attributes={"last_level": None, "last_ts": None, "history": []},
            )
        except Exception:
            pass

        self.interval_sec = int(cfg.get("interval_sec", 60))
        self.history_window_minutes = int(cfg.get("history_window_minutes", 120))
        self.min_points = int(cfg.get("min_points", 5))
        self.trend_epsilon = float(cfg.get("trend_epsilon", 0.2))

        self.history_file_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "ai_predictive_humidity_history.json")
        )

        self.history = {}
        self.load_history()

        self.run_every(self.update_loop, "now", self.interval_sec)
        self.log_h(f"AI predikcija vlage {self.version} pokrenuta | sobe: {len(self.rooms)}")

    def update_loop(self, kwargs):
        now = time.time()
        cutoff = now - (self.history_window_minutes * 60)

        for room_name, room_info in self.rooms.items():
            humidity_sensor = room_info.get("humidity_sensor")
            if not humidity_sensor:
                continue

            value = self.get_float(humidity_sensor)
            if value is None:
                continue

            series = self.history.setdefault(room_name, [])
            series.append({"ts": now, "value": value})
            series = [p for p in series if p["ts"] >= cutoff]
            self.history[room_name] = series

            preds = self.compute_predictions(series, room_name)
            window_open = self.is_any_window_open(room_info.get("window_sensors", []))

            for label, pred in preds.items():
                sensor_id = f"sensor.predict_humidity_{room_name}_{label}"
                attrs = {
                    "friendly_name": f"{room_name} vlaga za {label}",
                    "unit_of_measurement": "%",
                    "soba": room_name,
                    "window_open": window_open,
                    "samples": len(series),
                    "trend": self.trend_label(pred - value),
                    "current": round(value, 1),
                }
                self.set_state(sensor_id, state=round(pred, 1), attributes=attrs)

        self.save_history_throttled()

    def compute_predictions(self, series, room_name):
        windows = {
            "15m": 15,
            "30m": 30,
            "1h": 60,
        }
        result = {}
        if len(series) < self.min_points:
            last = series[-1]["value"] if series else 0.0
            for k in windows:
                result[k] = last
            return result

        now = series[-1]["ts"]
        last = series[-1]["value"]

        for label, minutes in windows.items():
            cutoff = now - minutes * 60
            recent = [p for p in series if p["ts"] >= cutoff]
            if len(recent) < 2:
                result[label] = last
                continue

            first = recent[0]
            dt = (recent[-1]["ts"] - first["ts"]) / 60.0
            if dt <= 0:
                result[label] = last
                continue

            rate_per_min = (recent[-1]["value"] - first["value"]) / dt
            horizon = 60 if label == "1h" else (30 if label == "30m" else 15)
            pred = last + rate_per_min * horizon
            pred = max(0.0, min(100.0, pred))
            self.log_h(
                f"Predikcija {label} | soba={room_name} | rate_per_min={rate_per_min:.3f} | pred={pred:.1f}",
                level="DEBUG",
            )
            result[label] = pred

        return result

    def trend_label(self, delta):
        if delta >= self.trend_epsilon:
            return "rastu"
        if delta <= -self.trend_epsilon:
            return "pada"
        return "stabilno"

    def is_any_window_open(self, sensors):
        if isinstance(sensors, str):
            sensors = [sensors]
        if not isinstance(sensors, list):
            return False
        for ent in sensors:
            if self.get_state(ent) == "on":
                return True
        return False

    def get_float(self, entity):
        try:
            val = self.get_state(entity)
            if val in (None, "unknown", "unavailable"):
                return None
            return float(val)
        except Exception:
            return None

    def load_history(self):
        if not os.path.exists(self.history_file_path):
            return
        try:
            with open(self.history_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.history = {
                    k: [p for p in v if isinstance(p, dict) and "ts" in p and "value" in p]
                    for k, v in data.items()
                }
        except Exception:
            return

    def save_history_throttled(self):
        now = time.time()
        last = getattr(self, "_last_save_ts", 0)
        if now - last < 30:
            return
        self._last_save_ts = now
        try:
            with open(self.history_file_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f)
        except Exception:
            return

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

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[PREDIKCIJA VLAGE] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

