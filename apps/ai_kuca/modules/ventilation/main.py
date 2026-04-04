#
# AI Ventilacija Main v0.1 (skeleton)
#
# Ova skripta trenutno samo ucitava room_configs.yaml iz nadfoldera.
# Logiku ventilacije dodajemo nakon sto potvrdimo senzore i pragove.
#

import os
from datetime import datetime
import time
import json
from datetime import datetime, timezone
from collections import deque
from ai_kuca.core.base_app import BaseApp
from ai_kuca.core.logger import push_log_to_ha


class AIVentilacijaMain(BaseApp):
    """
    Klasa za kontrolu ventilacije soba na temelju vlage.
    
    Upravlja ventilatorima u sobama koristeÄ‡i baseline vlagu iz povijesti,
    s pragovima za ukljuÄŤivanje/iskljuÄŤivanje, minimalnim vremenima rada
    i pauzama, te provjerom vanjske vlage i prozora.
    """
    def initialize(self):
        self.init_base()
        system_cfg = self.load_system_config()
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "ventilation", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))
        self.version = "V1." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        self.log_h(f"AI ventilacija {self.version} pokrenuta", level="INFO")
        """
        Inicijalizira AIVentilacijaMain skriptu.
        
        UÄŤitava konfiguraciju soba i sustava, postavlja pragove i uÄŤitava povijest.
        PokreÄ‡e glavnu petlju svakih interval_sec sekundi.
        """
        self.room_configs = self.load_yaml_file("room_configs.yaml")

        system_cfg = self.load_system_config()
        ventilation_cfg = system_cfg.get("ventilation", {})
        self.forecast_entity = ventilation_cfg.get("forecast_entity")
        self.outdoor_humidity_sensor = ventilation_cfg.get("outdoor_humidity_sensor")
        self.log_level = system_cfg.get("logging_level", "INFO")

        if not self.forecast_entity and not self.outdoor_humidity_sensor:
            self.log_h(
                "Nedostaje konfiguracija: ventilation.forecast_entity i ventilation.outdoor_humidity_sensor; ventilacija neÄ‡e raditi",
                level="ERROR",
            )
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "ventilation", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.interval_sec = int(ventilation_cfg.get("interval_sec", 60))
        self.baseline_window_sec = int(
            ventilation_cfg.get("baseline_window_minutes", 120)
        ) * 60
        self.delta_on_default = float(ventilation_cfg.get("delta_on", 8.0))
        self.delta_off_default = float(ventilation_cfg.get("delta_off", 4.0))
        self.abs_on_default = float(ventilation_cfg.get("abs_on", 70.0))
        self.abs_off_default = float(ventilation_cfg.get("abs_off", 60.0))
        self.min_on_sec_default = int(ventilation_cfg.get("min_on_sec", 300))
        self.min_off_sec_default = int(ventilation_cfg.get("min_off_sec", 180))
        self.min_samples_default = int(ventilation_cfg.get("min_samples", 5))
        self.outdoor_humidity_max = float(ventilation_cfg.get("outdoor_humidity_max", 80.0))
        self.allow_if_outdoor_unknown = bool(
            ventilation_cfg.get("allow_if_outdoor_unknown", True)
        )
        self.window_pause = bool(ventilation_cfg.get("window_pause", True))
        self.pause_switches = ventilation_cfg.get("pause_switches", [])
        if isinstance(self.pause_switches, str):
            self.pause_switches = [self.pause_switches]
        if not isinstance(self.pause_switches, list):
            self.pause_switches = []

        self.history_file_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "ai_ventilacija_history.json")
        )
        self.stats_file_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "ai_ventilacija_stats.json")
        )
        self.state_file_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "ai_ventilacija_state.json")
        )
        self.history = {}
        self.last_change = {}
        self.forecast_missing_logged = False
        self.pause_state = False
        self.load_history()
        self.load_runtime_state()
        self.ensure_runtime_state_file()

        self.run_every(self.main_loop, "now", self.interval_sec)
        fan_rooms = [
            r for r, c in self.room_configs.items() if c.get("fan") and c.get("humidity_sensor")
        ]
        self.log_h(f"AI Ventilacija {self.version} pokrenuta | sobe s fan: {len(fan_rooms)}", level="INFO")
        self.log_h(
            f"Konfiguracija | interval={self.interval_sec}s | baza={self.baseline_window_sec//60}m | delta_on={self.delta_on_default} | delta_off={self.delta_off_default}",
            level="DEBUG",
        )

    def main_loop(self, kwargs):
        now = time.time()
        state_changed = False
        paused = self.any_pause_active()
        if paused != self.pause_state:
            self.pause_state = paused
            self.log_h(f"Ventilacija pauza: {'UKLJ' if paused else 'ISKLJ'}", level="INFO")
        outdoor_humidity = None if paused else self.get_outdoor_humidity()
        self.log_h(
            f"Vanjska vlaga | vrijednost={outdoor_humidity} | pauza={paused}",
            level="DEBUG",
        )

        for room_name, cfg in self.room_configs.items():
            humidity_sensor = cfg.get("humidity_sensor")
            if not humidity_sensor:
                continue

            humidity = self.get_humidity(humidity_sensor)
            if humidity is None:
                self.notify_missing_sensor(humidity_sensor, module_name="AIVentilacijaMain", cooldown_sec=900)
                continue

            self.append_history(room_name, now, humidity)

            baseline = humidity
            if self.history[room_name]:
                baseline = min(v for (_, v) in self.history[room_name])
            self.log_h(
                f"Soba {room_name} | vlaga={humidity:.1f} | baza={baseline:.1f} | uzoraka={len(self.history[room_name])}",
                level="DEBUG",
            )

            fan_entity = cfg.get("fan")
            if not fan_entity:
                continue

            vent_cfg = cfg.get("ventilation", {}) or {}
            delta_on = float(vent_cfg.get("delta_on", self.delta_on_default))
            delta_off = float(vent_cfg.get("delta_off", self.delta_off_default))
            abs_on = float(vent_cfg.get("abs_on", self.abs_on_default))
            abs_off = float(vent_cfg.get("abs_off", self.abs_off_default))
            min_on_sec = int(vent_cfg.get("min_on_sec", self.min_on_sec_default))
            min_off_sec = int(vent_cfg.get("min_off_sec", self.min_off_sec_default))
            min_samples = int(vent_cfg.get("min_samples", self.min_samples_default))

            if len(self.history[room_name]) < min_samples:
                on_threshold = abs_on
                off_threshold = abs_off
            else:
                on_threshold = max(baseline + delta_on, abs_on)
                off_threshold = max(baseline + delta_off, abs_off)
            self.log_h(
                f"Soba {room_name} | prag_uklj={on_threshold:.1f} | prag_isklj={off_threshold:.1f} | min_uzoraka={min_samples}",
                level="DEBUG",
            )
            self.log_h(
                f"Soba {room_name} | racun_pragova: on=max({baseline:.1f}+{delta_on:.1f}, {abs_on:.1f})={on_threshold:.1f} | off=max({baseline:.1f}+{delta_off:.1f}, {abs_off:.1f})={off_threshold:.1f}",
                level="DEBUG",
            )

            window_sensors = cfg.get("window_sensors") or cfg.get("window_sensor")
            if isinstance(window_sensors, str):
                window_sensors = [window_sensors]
            if not isinstance(window_sensors, list):
                window_sensors = []
            window_open = self.any_window_open(window_sensors)
            self.log_h(f"Soba {room_name} | prozor_otvoren={window_open}", level="DEBUG")

            fan_on = self.get_state(fan_entity) == "on"
            last = self.last_change.get(room_name, 0)
            self.log_h(
                f"Soba {room_name} | ventilator_uklj={fan_on} | zadnja_promjena={last}",
                level="DEBUG",
            )

            if paused:
                if fan_on:
                    self.log_h(
                        f"VENT {room_name}: ISKLJ (pauza) | VLAGA {humidity:.1f}% | "
                        f"BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%"
                    )
                    self.turn_fan(fan_entity, False, room_name, humidity, baseline)
                    self.last_change[room_name] = now
                    state_changed = True
                continue

            if fan_on:
                if (now - last) < min_on_sec:
                    self.log_h(
                        f"Soba {room_name} | min_uklj aktivan ({now - last:.0f}s/{min_on_sec}s)",
                        level="DEBUG",
                    )
                    continue
                if self.window_pause and window_open:
                    self.log_h(
                        f"VENT {room_name}: ISKLJ (prozor) | VLAGA {humidity:.1f}% | "
                        f"BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%"
                    )
                    self.turn_fan(fan_entity, False, room_name, humidity, baseline)
                    self.last_change[room_name] = now
                    state_changed = True
                    continue
                if humidity <= off_threshold:
                    self.log_h(
                        f"VENT {room_name}: ISKLJ (prag) | VLAGA {humidity:.1f}% | "
                        f"BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%"
                    )
                    self.turn_fan(fan_entity, False, room_name, humidity, baseline)
                    self.last_change[room_name] = now
                    state_changed = True
                continue

            if (now - last) < min_off_sec:
                self.log_h(
                    f"Soba {room_name} | min_isklj aktivan ({now - last:.0f}s/{min_off_sec}s)",
                    level="DEBUG",
                )
                continue

            if self.window_pause and window_open:
                continue

            if outdoor_humidity is None and not self.allow_if_outdoor_unknown:
                self.log_h(
                    f"VENT {room_name}: PRESKOCI (nema vanjske vlage) | VLAGA {humidity:.1f}% | "
                    f"BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%",
                    level="WARNING",
                )
                continue

            if outdoor_humidity is not None and outdoor_humidity > self.outdoor_humidity_max:
                self.log_h(
                    f"VENT {room_name}: PRESKOCI (vanjska vlaga {outdoor_humidity:.1f}% > {self.outdoor_humidity_max:.1f}%) | "
                    f"VLAGA {humidity:.1f}% | BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%",
                    level="DEBUG",
                )
                continue

            if humidity >= on_threshold:
                self.turn_fan(fan_entity, True, room_name, humidity, baseline)
                self.last_change[room_name] = now
                state_changed = True
            else:
                self.log_h(
                    f"VENT {room_name}: PRESKOCI (ispod praga ukljucivanja) | VLAGA {humidity:.1f}% | "
                    f"BAZA {baseline:.1f}% | PRAG_UKLJ {on_threshold:.1f}% | PRAG_ISKLJ {off_threshold:.1f}%",
                    level="INFO",
                )

        self.save_history()
        self.save_stats(now)
        if state_changed:
            self.save_runtime_state()

        return

    def turn_fan(self, entity, turn_on, room_name, humidity, baseline):
        service = "fan/turn_on" if turn_on else "fan/turn_off"
        self.call_service(service, entity_id=entity)
        state = "UKLJ" if turn_on else "ISKLJ"
        self.log_h(
            f"VENT {room_name}: {state} | VLAGA {humidity:.1f}% | BAZA {baseline:.1f}%"
        )

    def get_outdoor_humidity(self):
        if self.outdoor_humidity_sensor:
            val = self.get_humidity(self.outdoor_humidity_sensor)
            if val is not None:
                self.log_h(
                    f"Vanjska vlaga (senzor) | {self.outdoor_humidity_sensor} = {val:.1f}%",
                    level="DEBUG",
                )
                return val
            self.notify_missing_sensor(self.outdoor_humidity_sensor, module_name="AIVentilacijaMain", cooldown_sec=900)

        forecast = None
        if self.forecast_entity:
            forecast = self.get_state(self.forecast_entity, attribute="forecast")

        if not isinstance(forecast, list) or not forecast:
            if not self.forecast_missing_logged:
                self.log_h(
                    f"VENT: prognoza nedostaje/prazna za {self.forecast_entity} (atribut 'forecast')",
                    level="WARNING",
                )
                self.forecast_missing_logged = True
            return None
        self.forecast_missing_logged = False

        target_ts = time.time() + 3600
        best = None
        best_dt = None

        for item in forecast:
            dt_str = item.get("datetime") or item.get("time")
            humidity = item.get("humidity") or item.get("relative_humidity")
            if dt_str is None or humidity is None:
                continue

            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = dt.timestamp()
            except Exception:
                continue

            diff = ts - target_ts
            if diff < 0:
                continue

            if best is None or diff < best_dt:
                best = humidity
                best_dt = diff

        if best is None:
            for item in forecast:
                humidity = item.get("humidity") or item.get("relative_humidity")
                if humidity is not None:
                    return float(humidity)
            return None

        try:
            return float(best)
        except Exception:
            return None

    def any_window_open(self, sensors):
        for ent in sensors:
            state = self.get_state(ent)
            if state == "on" or state == "open" or state == "true":
                return True
        return False

    def any_pause_active(self):
        for ent in self.pause_switches:
            state = self.get_state(ent)
            if state == "on" or state == "true":
                return True
        return False

    def get_humidity(self, entity):
        try:
            val = self.get_state(entity)
            if val in (None, "unknown", "unavailable"):
                return None
            return float(val)
        except Exception:
            return None

    def append_history(self, room_name, now, humidity):
        if room_name not in self.history:
            self.history[room_name] = deque()
        self.history[room_name].append((now, humidity))

        cutoff = now - self.baseline_window_sec
        while self.history[room_name] and self.history[room_name][0][0] < cutoff:
            self.history[room_name].popleft()

    def load_history(self):
        now = time.time()
        cutoff = now - self.baseline_window_sec
        try:
            with open(self.history_file_path, "r", encoding="utf-8") as f:
                raw_history = json.load(f) or {}
        except FileNotFoundError:
            self.log_h(
                f"VENT: history file ne postoji, start s praznom povijesti | path={self.history_file_path}",
                level="INFO",
            )
            return
        except Exception as ex:
            self.log_h(
                f"VENT: greska pri ucitavanju history filea {self.history_file_path}: {ex}",
                level="WARNING",
            )
            return

        restored_rooms = []
        invalid_entries = 0
        for room_name, entries in raw_history.items():
            if not isinstance(entries, list):
                continue
            history = deque()
            for entry in entries:
                if not isinstance(entry, list) or len(entry) != 2:
                    continue
                try:
                    ts = float(entry[0])
                    humidity = float(entry[1])
                except Exception:
                    invalid_entries += 1
                    continue
                if ts >= cutoff:
                    history.append((ts, humidity))
            if history:
                self.history[room_name] = history
                restored_rooms.append(f"{room_name} ({len(history)})")

        if restored_rooms:
            rooms_text = ", ".join(restored_rooms)
            self.log_h(
                f"VENT: vracen history iz zadnja {self.baseline_window_sec // 60} min za {rooms_text}",
                level="INFO",
            )
        if invalid_entries:
            self.log_h(
                f"VENT: preskoceni neispravni history zapisi | broj={invalid_entries} | path={self.history_file_path}",
                level="DEBUG",
            )

    def load_runtime_state(self):
        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                raw_state = json.load(f) or {}
        except FileNotFoundError:
            self.log_h(
                f"VENT: runtime state file ne postoji, koristi se default stanje | path={self.state_file_path}",
                level="INFO",
            )
            return
        except Exception as ex:
            self.log_h(
                f"VENT: greska pri ucitavanju state filea {self.state_file_path}: {ex}",
                level="WARNING",
            )
            return

        raw_last_change = raw_state.get("last_change", {})
        if not isinstance(raw_last_change, dict):
            return

        restored_rooms = []
        invalid_state_entries = 0
        for room_name, ts in raw_last_change.items():
            try:
                self.last_change[room_name] = float(ts)
                restored_rooms.append(room_name)
            except Exception:
                invalid_state_entries += 1
                continue

        if restored_rooms:
            self.log_h(
                f"VENT: vracen runtime state za sobe: {', '.join(restored_rooms)}",
                level="INFO",
            )
        if invalid_state_entries:
            self.log_h(
                f"VENT: preskoceni neispravni runtime zapisi | broj={invalid_state_entries} | path={self.state_file_path}",
                level="DEBUG",
            )

    def ensure_runtime_state_file(self):
        if os.path.exists(self.state_file_path):
            return
        self.save_runtime_state()

    def save_stats(self, now):
        stats = {
            "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "window_minutes": self.baseline_window_sec // 60,
            "rooms": {},
        }

        for room_name, entries in self.history.items():
            if not entries:
                continue
            values = [humidity for (_, humidity) in entries]
            stats["rooms"][room_name] = {
                "samples": len(values),
                "current": round(values[-1], 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "avg": round(sum(values) / len(values), 2),
            }

        try:
            with open(self.stats_file_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=True, indent=2)
        except Exception as ex:
            self.log_h(
                f"VENT: greska pri spremanju stats filea {self.stats_file_path}: {ex}",
                level="WARNING",
            )

    def save_history(self):
        now = time.time()
        cutoff = now - self.baseline_window_sec
        payload = {}
        for room_name, entries in self.history.items():
            filtered = []
            for ts, humidity in entries:
                if ts >= cutoff:
                    filtered.append([round(ts, 3), round(humidity, 3)])
            if filtered:
                payload[room_name] = filtered

        try:
            with open(self.history_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True)
        except Exception as ex:
            self.log_h(
                f"VENT: greska pri spremanju history filea {self.history_file_path}: {ex}",
                level="WARNING",
            )

    def save_runtime_state(self):
        payload = {"last_change": {}}
        for room_name, ts in self.last_change.items():
            try:
                payload["last_change"][room_name] = round(float(ts), 3)
            except Exception:
                continue

        try:
            with open(self.state_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True, indent=2)
        except Exception as ex:
            self.log_h(
                f"VENT: greska pri spremanju state filea {self.state_file_path}: {ex}",
                level="WARNING",
            )

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[VENTILACIJA] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)



