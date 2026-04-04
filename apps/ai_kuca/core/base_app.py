import appdaemon.plugins.hass.hassapi as hass
import json
import os
import time
import threading
import fcntl
from ai_kuca.core.config_loader import ConfigLoader
from ai_kuca.core.logger import push_log_to_ha
from ai_kuca.core.notifications import send_missing_sensor_notifications
from ai_kuca.core.utils import as_float


class BaseApp(hass.Hass):
    """Shared helpers for ai_kuca apps."""

    _json_state_lock = threading.Lock()

    def _json_lock_path(self, path):
        return f"{path}.lock"

    def init_base(self):
        self.config_loader = ConfigLoader(self)
        self._missing_sensor_alert_state_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "config", "sensor_alert_state.json")
        )
        self._target_writer_state_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "config", "target_writer_state.json")
        )
        self._notify_group_service = "notify/svi_mobiteli"
        self._notify_device_services = [
            "notify/mobile_app_xiaomi_renata",
            "notify/mobile_app_htc_desire_650",
            "notify/mobile_app_samsung",
            "notify/mobile_app_dashboard_tablet",
            "notify/mobile_app_xiaomi_redmi_note_10_5g_zmaj",
        ]

    def load_yaml_file(self, filename):
        return self.config_loader.load_yaml(filename)

    def load_system_config(self):
        return self.load_yaml_file("system_configs.yaml")

    def _load_json_state(self, path):
        with self._json_state_lock:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(self._json_lock_path(path), "a", encoding="utf-8") as lock_f:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f) or {}
                        return data if isinstance(data, dict) else {}
                    finally:
                        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            except Exception:
                return {}

    def _save_json_state(self, path, data):
        with self._json_state_lock:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                lock_path = self._json_lock_path(path)
                with open(lock_path, "a", encoding="utf-8") as lock_f:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                    try:
                        tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
                        with open(tmp_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=True)
                        os.replace(tmp_path, path)
                    finally:
                        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
                return True
            except Exception:
                return False

    def notify_missing_sensor(self, sensor_name, module_name="unknown", cooldown_sec=900):
        now = time.time()
        state = self._load_json_state(self._missing_sensor_alert_state_path)
        key = f"{module_name}:{sensor_name}"
        last_ts = float(state.get(key, 0) or 0)
        if now - last_ts < float(cooldown_sec):
            return False

        message = (
            f"UPOZORENJE!!! SENZOR ({sensor_name}) KOJI JE POTREBAN ZA RAD "
            f"({module_name}) JE NEDOSTUPAN!! SYSTEM NE RADI KAKO TREBA!!!"
        )

        status = send_missing_sensor_notifications(
            self,
            message,
            self._notify_group_service,
            self._notify_device_services,
        )

        state[key] = now
        self._save_json_state(self._missing_sensor_alert_state_path, state)
        self.log(
            f"[ALERT] Missing sensor notified | module={module_name} | sensor={sensor_name} | telegram={status.get('telegram')} | group={status.get('group')} | devices_sent={status.get('devices_sent')}",
            level="WARNING",
        )
        return True

    def ensure_required_sensors(self, sensor_map, module_name="unknown", cooldown_sec=900):
        missing_any = False
        for sensor_label, entity_id in (sensor_map or {}).items():
            if not entity_id:
                continue
            state = self.get_state(entity_id)
            if state in (None, "unknown", "unavailable"):
                missing_any = True
                self.notify_missing_sensor(entity_id, module_name=module_name, cooldown_sec=cooldown_sec)
                self.log(
                    f"[ALERT] Required sensor unavailable | module={module_name} | name={sensor_label} | entity={entity_id}",
                    level="ERROR",
                )
        return not missing_any

    def set_climate_target_guarded(self, entity_id, temperature, owner, priority, ttl_sec=120):
        now = time.time()
        state = self._load_json_state(self._target_writer_state_path)
        lock = state.get(entity_id) if isinstance(state.get(entity_id), dict) else {}

        lock_owner = str(lock.get("owner", ""))
        lock_prio = int(lock.get("priority", -1))
        lock_exp = float(lock.get("expires_at", 0) or 0)
        lock_active = lock_exp > now

        if lock_active and lock_owner != owner and lock_prio > int(priority):
            self.log(
                f"[TARGET GUARD] Blocked write | entity={entity_id} | owner={owner} | priority={priority} | held_by={lock_owner}({lock_prio})",
                level="DEBUG",
            )
            return False

        try:
            self.call_service(
                "climate/set_temperature",
                entity_id=entity_id,
                temperature=round(float(temperature), 2),
            )
        except Exception as ex:
            self.log(
                f"[TARGET GUARD] Write failed | entity={entity_id} | owner={owner} | err={ex}",
                level="WARNING",
            )
            return False

        state[entity_id] = {
            "owner": owner,
            "priority": int(priority),
            "expires_at": now + float(ttl_sec),
        }
        self._save_json_state(self._target_writer_state_path, state)
        return True

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
