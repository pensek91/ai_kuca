# AI Heating Predictive Sensors V3.6 (15m/30m/1h predictions)

import os
from datetime import datetime
import time
import math
import yaml
import json
from datetime import datetime, timezone
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class PredictiveSensors(hass.Hass):
    """
    Klasa za prediktivne senzore temperature soba.
    Sada podržava pametni boost: automatski može privremeno povisiti target iznad ručno unesenog,
    a kad se približi, vraća ga na ručni target. Svi parametri su konfigurabilni.
    """
    def initialize(self):
        self.last_auto_target = {}
        """
        Inicijalizira PredictiveSensors skriptu.
        
        UÄŤitava konfiguraciju, postavlja prozore povijesti i koeficijente,
        te pokreÄ‡e petlju aĹľuriranja svakih 60 sekundi.
        """
        self.version = "V3." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        config_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "room_configs.yaml")
        )
        with open(config_path, "r", encoding="utf-8") as f:
            self.rooms = yaml.safe_load(f) or {}

        system_cfg = self.load_system_config()
        predictive_cfg = system_cfg.get("predictive", {})
        heating_cfg = system_cfg.get("heating_main", {})
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "predictive_temperature", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.outdoor_temp_sensors = predictive_cfg.get("outdoor_temp_sensors") or []
        if isinstance(self.outdoor_temp_sensors, str):
            self.outdoor_temp_sensors = [self.outdoor_temp_sensors]
        if not isinstance(self.outdoor_temp_sensors, list):
            self.outdoor_temp_sensors = []
        self.forecast_entity = predictive_cfg.get("forecast_entity")
        self.pump_switch = predictive_cfg.get("pump_switch")

        # windows
        self.window_short_minutes = int(predictive_cfg.get("window_short_minutes", 15))
        self.window_long_minutes = int(predictive_cfg.get("window_long_minutes", 60))
        self.min_points_short = int(predictive_cfg.get("min_points_short", 5))
        self.min_points_long = int(predictive_cfg.get("min_points_long", 10))

        # loss coefficient (C/s per C diff); can be overridden per-room
        self.loss_coeff_default = float(predictive_cfg.get("loss_coeff_default", 0.00005))
        self.window_loss_multiplier = float(
            predictive_cfg.get("window_loss_multiplier", 3.0)
        )

        # blend weights
        self.weight_short = float(predictive_cfg.get("weight_short", 0.3))
        self.weight_long = float(predictive_cfg.get("weight_long", 0.7))
        self.recommended_target_max_adjust = float(
            predictive_cfg.get("recommended_target_max_adjust", 2.0)
        )
        self.auto_apply_targets = bool(predictive_cfg.get("auto_apply_targets", False))
        self.auto_apply_deadband = float(predictive_cfg.get("auto_apply_deadband", 0.2))
        self.auto_apply_max_step_per_cycle = float(
            predictive_cfg.get("auto_apply_max_step_per_cycle", 0.5)
        )
        self.auto_apply_skip_when_overheat = bool(
            predictive_cfg.get("auto_apply_skip_when_overheat", True)
        )
        self.overheat_switch = heating_cfg.get("overheat_switch")
        self.max_room_temp = float(heating_cfg.get("max_room_temp", 35.0))
        self.min_room_temp = float(heating_cfg.get("min_room_temp", 8.0))

        self.history = {}
        self.heating_rate = {}
        self.cooling_rate = {}
        self.heat_lost_rate = {}
        self.forecast_missing_logged = False
        self.history_file_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "ai_predictive_history.json")
        )
        self.load_history()

        self.run_every(self.update_loop, "now", 60)
        self.log_h(f"AI predikcija {self.version} pokrenuta | sobe: {len(self.rooms)}")
        self.log_h(
            f"Konfiguracija | prozor_kratko={self.window_short_minutes}m | prozor_dugo={self.window_long_minutes}m",
            level="DEBUG",
        )
        self.log_h(
            f"Target auto-mode | enabled={self.auto_apply_targets} | deadband={self.auto_apply_deadband} | max_step={self.auto_apply_max_step_per_cycle}",
            level="DEBUG",
        )

    def update_loop(self, kwargs):
        now = time.time()
        short_sec = self.window_short_minutes * 60
        long_sec = self.window_long_minutes * 60

        outdoor_sensor_temp = self.get_outdoor_temp_avg()
        outdoor_forecast = self.get_forecast_temp(1)
        if outdoor_forecast is None and not self.forecast_missing_logged:
            self.forecast_missing_logged = True
            self.log_h("Prognoza nije dostupna (meteo entitet ili atributi)")
        outdoor_effective = self.pick_outdoor_temp(outdoor_sensor_temp, outdoor_forecast)
        self.log_h(
            f"Vanjska temp | senzor_prosjek={outdoor_sensor_temp} | prognoza={outdoor_forecast} | efektivna={outdoor_effective}",
            level="DEBUG",
        )

        pump_on = self.get_state(self.pump_switch) == "on"

        for room_name, cfg in self.rooms.items():
            climate_entity = cfg.get("climate")
            temp_sensor = cfg.get("temp_sensor")
            loss_coeff = cfg.get("loss_coeff", self.loss_coeff_default)
            room_pred_cfg = self.get_room_predictive_cfg(cfg)

            window_sensors = cfg.get("window_sensors") or cfg.get("window_sensor")
            if isinstance(window_sensors, str):
                window_sensors = [window_sensors]
            if not isinstance(window_sensors, list):
                window_sensors = []

            window_open = self.any_window_open(window_sensors)
            if window_open:
                loss_coeff = loss_coeff * self.window_loss_multiplier
            self.log_h(
                f"Soba {room_name} | prozor_otvoren={window_open} | koef_gubitka={loss_coeff}",
                level="DEBUG",
            )

            curr_temp = None
            if temp_sensor:
                curr_temp = self.get_sensor_temp(temp_sensor)

            if curr_temp is None and climate_entity:
                curr_temp = self.get_climate_temp(climate_entity)

            if curr_temp is None:
                continue

            if room_name not in self.history:
                self.history[room_name] = []
            self.history[room_name].append((now, curr_temp))

            cutoff_long = now - long_sec
            self.history[room_name] = [(t, v) for (t, v) in self.history[room_name] if t >= cutoff_long]

            short_hist = [(t, v) for (t, v) in self.history[room_name] if t >= now - short_sec]
            long_hist = self.history[room_name]

            if len(short_hist) < self.min_points_short or len(long_hist) < self.min_points_long:
                self.publish_recommended_target(
                    room_name=room_name,
                    cfg=cfg,
                    curr_temp=curr_temp,
                    pred_1h=curr_temp,
                    prediction_ready=False,
                    reason="insufficient_history",
                )
                self.log_h(
                    f"Soba {room_name} | premalo podataka (kratko={len(short_hist)}, dugo={len(long_hist)})",
                    level="DEBUG",
                )
                continue

            slope_short = self.calc_slope(short_hist)
            slope_long = self.calc_slope(long_hist)
            if slope_short is None or slope_long is None:
                continue

            slope = self.weight_short * slope_short + self.weight_long * slope_long
            self.log_h(
                f"Soba {room_name} | nagib_kratko={slope_short:.6f} | nagib_dugo={slope_long:.6f} | nagib={slope:.6f}",
                level="DEBUG",
            )

            # baziraj na stvarnom trendu
            base_rate = slope

            correction = 0.0
            if outdoor_effective is not None:
                correction = loss_coeff * (curr_temp - outdoor_effective)

            # korekciju ograniÄŤi na 50% stvarnog trenda da ne preokrene smjer
            max_corr = abs(base_rate) * 0.5
            if max_corr > 0:
                correction = max(-max_corr, min(max_corr, correction))

            effective_rate = base_rate - correction
            self.log_h(
                f"Soba {room_name} | bazna_stopa={base_rate:.6f} | korekcija={correction:.6f} | efektivna_stopa={effective_rate:.6f}",
                level="DEBUG",
            )

            # predictions
            pred_15m = curr_temp + effective_rate * 900
            pred_30m = curr_temp + effective_rate * 1800
            pred_1h = curr_temp + effective_rate * 3600
            self.log_h(
                f"Soba {room_name} | T={curr_temp:.2f} | 15m={pred_15m:.2f} | 30m={pred_30m:.2f} | 1h={pred_1h:.2f}",
                level="DEBUG",
            )

            if not math.isfinite(pred_1h):
                continue

            delta_pred = pred_1h - curr_temp
            if delta_pred > 0.1:
                trend = "heating"
            elif delta_pred < -0.1:
                trend = "cooling"
            else:
                trend = "steady"

            self.set_state(
                f"sensor.predict_{room_name}_1h",
                state=str(round(pred_1h, 1)),
                attributes={
                    "friendly_name": f"{room_name} temperatura za 1h",
                    "unit_of_measurement": "C",
                    "soba": room_name,
                    "trend": trend,
                    "window_open": window_open,
                    "outdoor_effective": outdoor_effective,
                },
            )

            # trend za 15m/30m
            trend_15m = "steady"
            delta_15m = pred_15m - curr_temp
            if delta_15m > 0.1:
                trend_15m = "heating"
            elif delta_15m < -0.1:
                trend_15m = "cooling"

            trend_30m = "steady"
            delta_30m = pred_30m - curr_temp
            if delta_30m > 0.1:
                trend_30m = "heating"
            elif delta_30m < -0.1:
                trend_30m = "cooling"

            if math.isfinite(pred_15m):
                self.set_state(
                    f"sensor.predict_{room_name}_15m",
                    state=str(round(pred_15m, 1)),
                    attributes={
                        "friendly_name": f"{room_name} temperatura za 15m",
                        "unit_of_measurement": "C",
                        "soba": room_name,
                        "trend": trend_15m,
                        "window_open": window_open,
                    },
                )

            if math.isfinite(pred_30m):
                self.set_state(
                    f"sensor.predict_{room_name}_30m",
                    state=str(round(pred_30m, 1)),
                    attributes={
                        "friendly_name": f"{room_name} temperatura za 30m",
                        "unit_of_measurement": "C",
                        "soba": room_name,
                        "trend": trend_30m,
                        "window_open": window_open,
                    },
                )

            # --- NOVO: pametni boost logika ---
            manual_target = cfg.get("manual_target")
            if manual_target is None:
                manual_target = curr_temp  # ili current_target ako postoji
            boost_target = manual_target
            smart_boost_enabled = room_pred_cfg.get("smart_boost_enabled", False)
            smart_boost_delta = room_pred_cfg.get("smart_boost_delta", 2.0)
            smart_boost_max = room_pred_cfg.get("smart_boost_max", 25.0)
            if smart_boost_enabled and (manual_target - curr_temp) >= smart_boost_delta:
                boost_target = min(manual_target + smart_boost_delta, smart_boost_max)
            target_info = self.publish_recommended_target(
                room_name=room_name,
                cfg=cfg,
                curr_temp=curr_temp,
                pred_1h=pred_1h,
                room_pred_cfg=room_pred_cfg,
                manual_target=boost_target,
            )
            if (
                target_info
                and target_info.get("prediction_ready", True)
                and self.auto_apply_targets
                and target_info.get("room_auto_apply", True)
            ):
                self.maybe_apply_recommended_target(
                    room_name=room_name,
                    climate_entity=target_info["climate_entity"],
                    current_target=target_info["current_target"],
                    recommended=target_info["recommended"],
                    step=target_info["step"],
                    deadband=target_info["deadband"],
                    max_step_per_cycle=target_info["max_step_per_cycle"],
                    min_target=target_info["min_target"],
                    max_target=target_info["max_target"],
                    manual_target=boost_target,
                )

            self.heating_rate[room_name] = max(base_rate, 0.0)
            self.cooling_rate[room_name] = abs(min(base_rate, 0.0))
            # heat_lost_rate: brzina gubitka topline kroz zidove/prozore (C/s), korigirana za pumpu i prozore
            self.heat_lost_rate[room_name] = max(correction, 0.0)

            self.set_rate_state(f"sensor.{room_name}_heating_rate", self.heating_rate.get(room_name, 0))
            self.set_rate_state(f"sensor.{room_name}_cooling_rate", self.cooling_rate.get(room_name, 0))
            self.set_rate_state(f"sensor.{room_name}_heat_lost_rate", self.heat_lost_rate.get(room_name, 0))

        self.save_history(now, long_sec)

    def calc_slope(self, hist):
        first_t, first_v = hist[0]
        last_t, last_v = hist[-1]
        dt = last_t - first_t
        if dt <= 0:
            return None
        return (last_v - first_v) / dt

    def publish_recommended_target(self, room_name, cfg, curr_temp, pred_1h, room_pred_cfg=None, prediction_ready=True, reason="ok", manual_target=None):
        climate_entity = cfg.get("climate")
        if not climate_entity:
            return None

        room_pred_cfg = room_pred_cfg or {}
        room_auto_apply = self.coerce_bool(room_pred_cfg.get("auto_apply_targets"), True)
        effective_deadband = self.as_float(
            room_pred_cfg.get("deadband"),
            self.auto_apply_deadband,
        )
        effective_max_step = self.as_float(
            room_pred_cfg.get("max_step_per_cycle"),
            self.auto_apply_max_step_per_cycle,
        )
        effective_min_target = self.as_float(
            room_pred_cfg.get("min_temp"),
            self.min_room_temp,
        )
        effective_max_target = self.as_float(
            room_pred_cfg.get("max_temp"),
            self.max_room_temp,
        )

        target_source = "climate.temperature"
        current_target = self.get_climate_target(climate_entity)
        if current_target is None:
            target_source = "room_configs.target"
            current_target = self.as_float(cfg.get("target"))
        if current_target is None:
            return None

        step = self.get_target_step(cfg, climate_entity)
        diff = current_target - pred_1h

        # Informativna preporuka: bez automatskog set_temperature poziva.
        if abs(diff) < 0.2:
            adjustment = 0.0
        else:
            adjustment = max(-self.recommended_target_max_adjust, min(self.recommended_target_max_adjust, diff))
        raw_recommended = current_target + adjustment
        recommended = self.quantize_target(raw_recommended, step)

        sensor_id = f"sensor.predict_{room_name}_target_recommended"
        self.set_state(
            sensor_id,
            state=str(round(recommended, 2)),
            attributes={
                "friendly_name": f"{room_name} preporuceni target",
                "unit_of_measurement": "C",
                "soba": room_name,
                "mode": "suggestion_only",
                "auto_apply_enabled": False,
                "prediction_ready": bool(prediction_ready),
                "reason": reason,
                "climate_entity": climate_entity,
                "room_auto_apply_targets": bool(room_auto_apply),
                "target_source": target_source,
                "current_target": round(current_target, 2),
                "current_temp": round(curr_temp, 2),
                "pred_1h": round(pred_1h, 2),
                "delta_target_minus_pred1h": round(diff, 2),
                "recommended_delta": round(recommended - current_target, 2),
                "target_step": step,
                "effective_deadband": round(effective_deadband, 3),
                "effective_max_step_per_cycle": round(effective_max_step, 3),
                "effective_min_target": round(effective_min_target, 2),
                "effective_max_target": round(effective_max_target, 2),
            },
        )
        return {
            "climate_entity": climate_entity,
            "current_target": current_target,
            "recommended": recommended,
            "step": step,
            "prediction_ready": bool(prediction_ready),
            "room_auto_apply": bool(room_auto_apply),
            "deadband": float(effective_deadband),
            "max_step_per_cycle": float(effective_max_step),
            "min_target": float(effective_min_target),
            "max_target": float(effective_max_target),
            "manual_target": manual_target,
        }

    def maybe_apply_recommended_target(
        self,
        room_name,
        climate_entity,
        current_target,
        recommended,
        step,
        deadband,
        max_step_per_cycle,
        min_target,
        max_target,
        manual_target=None,
    ):
        if self.auto_apply_skip_when_overheat and self.overheat_switch:
            if self.get_state(self.overheat_switch) == "on":
                self.log_h(
                    f"AUTO TARGET {room_name}: preskoceno (overheat aktivan)",
                    level="DEBUG",
                )
                return

        # --- NOVO: deadband prema manual_target ---
        # Dohvati deadband iz konfiguracije sobe (ili koristi default)
        smart_boost_deadband = 0.5
        if hasattr(self, 'rooms') and room_name in self.rooms:
            room_pred_cfg = self.get_room_predictive_cfg(self.rooms[room_name])
            smart_boost_deadband = room_pred_cfg.get("smart_boost_deadband", 0.5)
        if manual_target is not None and abs(recommended - manual_target) < smart_boost_deadband:
            recommended = manual_target

        delta = recommended - current_target
        if abs(delta) < deadband:
            return

        # Ako uređaj radi u koraku 1.0C, efektivni korak po ciklusu ne moze biti manji od 1.0C.
        max_step = max(max_step_per_cycle, step)
        limited = current_target + max(-max_step, min(max_step, recommended - current_target))
        limited = self.quantize_target(limited, step)
        limited = self.clamp_target(limited, min_target=min_target, max_target=max_target)

        if abs(limited - current_target) < 0.01:
            return

        try:
            self.call_service(
                "climate/set_temperature",
                entity_id=climate_entity,
                temperature=round(limited, 2),
            )
            self.log_h(
                f"AUTO TARGET {room_name}: {current_target:.2f} -> {limited:.2f} (pred_1h regulacija)",
                level="INFO",
            )
        except Exception as ex:
            self.log_h(
                f"AUTO TARGET {room_name}: neuspjelo postavljanje targeta ({ex})",
                level="WARNING",
            )

        self.last_auto_target[climate_entity] = limited

    def pick_outdoor_temp(self, sensor_temp, forecast_temp):
        if sensor_temp is None and forecast_temp is None:
            return None
        if sensor_temp is None:
            return forecast_temp
        if forecast_temp is None:
            return sensor_temp
        return sensor_temp if sensor_temp <= forecast_temp else forecast_temp

    def any_window_open(self, sensors):
        for ent in sensors:
            state = self.get_state(ent)
            if state == "on" or state == "open" or state == "true":
                return True
        return False

    def get_forecast_temp(self, hours_ahead):
        forecast = self.get_state(self.forecast_entity, attribute="forecast")
        if not isinstance(forecast, list) or not forecast:
            return None

        target_ts = time.time() + hours_ahead * 3600
        best = None
        best_dt = None

        for item in forecast:
            dt_str = item.get("datetime") or item.get("time")
            temp = item.get("temperature")
            if dt_str is None or temp is None:
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
                best = temp
                best_dt = diff

        if best is None:
            for item in forecast:
                temp = item.get("temperature")
                if temp is not None:
                    return float(temp)
            return None

        return float(best)

    def set_rate_state(self, entity_id, value):
        if not math.isfinite(value):
            return
        # Konvertiraj iz °C/s u °C/h (mnozi se s 3600)
        value_per_hour = value * 3600
        self.set_state(
            entity_id,
            state=str(round(value_per_hour, 2)),
            attributes={
                "friendly_name": entity_id.replace("sensor.", "").replace("_", " ").title(),
                "unit_of_measurement": "°C/h",
                "state_class": "measurement",
                "icon": "mdi:speedometer"
            }
        )

    def get_climate_target(self, entity):
        try:
            attr = self.get_state(entity, attribute="temperature")
            return self.as_float(attr)
        except Exception:
            return None

    def get_target_step(self, room_cfg, climate_entity):
        cfg_step = self.as_float(room_cfg.get("target_step"))
        if cfg_step and cfg_step > 0:
            return cfg_step

        try:
            step_attr = self.as_float(self.get_state(climate_entity, attribute="target_temp_step"))
            if step_attr and step_attr > 0:
                return step_attr
        except Exception:
            pass

        try:
            precision = self.as_float(self.get_state(climate_entity, attribute="precision"))
            if precision and precision > 0:
                return precision
        except Exception:
            pass

        return 0.5

    def quantize_target(self, value, step):
        if not step or step <= 0:
            return value
        q = round(float(value) / float(step)) * float(step)
        return round(q, 2)

    def clamp_target(self, value, min_target=None, max_target=None):
        if max_target is None:
            max_target = self.max_room_temp
        if min_target is None:
            min_target = self.min_room_temp
        value = min(value, max_target)
        value = max(value, min_target)
        return value

    def coerce_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("1", "true", "yes", "y", "da", "d", "on"):
                return True
            if v in ("0", "false", "no", "n", "ne", "off"):
                return False
            return default
        return bool(value)

    def get_room_predictive_cfg(self, room_cfg):
        pred = room_cfg.get("predictive", {})
        return pred if isinstance(pred, dict) else {}

    def get_climate_temp(self, entity):
        try:
            attr = self.get_state(entity, attribute="current_temperature")
            val = self.as_float(attr)
            if val is not None:
                return val

            attr = self.get_state(entity, attribute="temperature")
            return self.as_float(attr)
        except Exception:
            return None

    def get_sensor_temp(self, sensor_entity):
        return self.as_float(self.get_state(sensor_entity))

    def get_temp(self, entity):
        try:
            val = self.get_state(entity)
            if val in (None, "unknown", "unavailable"):
                return None
            return float(val)
        except Exception:
            return None

    def get_outdoor_temp_avg(self):
        values = []
        for ent in self.outdoor_temp_sensors:
            val = self.get_temp(ent)
            if val is not None:
                values.append(val)
        if not values:
            return None
        return sum(values) / len(values)

    def as_float(self, value, default=None):
        try:
            if value in (None, "unknown", "unavailable"):
                return default
            return float(value)
        except Exception:
            return default

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

    def load_history(self):
        now = time.time()
        cutoff = now - (self.window_long_minutes * 60)
        try:
            with open(self.history_file_path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except FileNotFoundError:
            return
        except Exception as ex:
            self.log_h(
                f"Greska pri ucitavanju povijesti predikcije {self.history_file_path}: {ex}",
                level="WARNING",
            )
            return

        restored = []
        for room_name, entries in raw.items():
            if not isinstance(entries, list):
                continue
            history = []
            for entry in entries:
                if not isinstance(entry, list) or len(entry) != 2:
                    continue
                try:
                    ts = float(entry[0])
                    temp = float(entry[1])
                except Exception:
                    continue
                if ts >= cutoff:
                    history.append((ts, temp))
            if history:
                self.history[room_name] = history
                restored.append(f"{room_name} ({len(history)})")

        if restored:
            self.log_h(
                f"Vracena povijest predikcije za {', '.join(restored)}",
                level="INFO",
            )

    def save_history(self, now, long_sec):
        cutoff = now - long_sec
        payload = {}
        for room_name, entries in self.history.items():
            filtered = []
            for ts, temp in entries:
                if ts >= cutoff:
                    filtered.append([round(ts, 3), round(temp, 3)])
            if filtered:
                payload[room_name] = filtered

        try:
            with open(self.history_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True)
        except Exception as ex:
            self.log_h(
                f"Greska pri spremanju povijesti predikcije {self.history_file_path}: {ex}",
                level="WARNING",
            )

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[PREDIKCIJA] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

