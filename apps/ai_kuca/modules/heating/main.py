#
# AI Heating Main V2.4 (global stop conditions)
# Hijerarhija:
# 1. Overheat preuzima kontrolu
# 2. Main odrzava sistem aktivnim bez prepisivanja rucnih targeta
# 3. ECO offset -2C / +2C relativno na trenutni target
# 4. Hladna pec pauzira sustav
#

import os
from datetime import datetime
import json
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class AIHeatingMain(hass.Hass):
    def initialize(self):
        self.version = "V2." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        system_cfg = self.load_system_config()
        heating_cfg = system_cfg.get("heating_main", {})
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "heating_main", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.active_switch = heating_cfg.get("active_switch")
        self.eco_switch = heating_cfg.get("eco_switch")
        self.eco_sync_source_switches = heating_cfg.get("eco_sync_source_switches") or []
        if isinstance(self.eco_sync_source_switches, str):
            self.eco_sync_source_switches = [self.eco_sync_source_switches]
        if not isinstance(self.eco_sync_source_switches, list):
            self.eco_sync_source_switches = []
        self.eco_sync_mode = str(heating_cfg.get("eco_sync_mode", "any_on")).lower()
        self.overheat_switch = heating_cfg.get("overheat_switch")
        self.flow_sensor = heating_cfg.get("flow_sensor")
        self.boiler_sensor = heating_cfg.get("boiler_sensor")
        self.outdoor_sensor = heating_cfg.get("outdoor_sensor")
        self.outdoor_temp_sensors = heating_cfg.get("outdoor_temp_sensors") or []
        if isinstance(self.outdoor_temp_sensors, str):
            self.outdoor_temp_sensors = [self.outdoor_temp_sensors]
        if not isinstance(self.outdoor_temp_sensors, list):
            self.outdoor_temp_sensors = []

        self.system_enabled = True
        missing = []
        for name, value in [
            ("heating_main.active_switch", self.active_switch),
            ("heating_main.eco_switch", self.eco_switch),
            ("heating_main.overheat_switch", self.overheat_switch),
            ("heating_main.flow_sensor", self.flow_sensor),
            ("heating_main.boiler_sensor", self.boiler_sensor),
            ("heating_main.outdoor_sensor", self.outdoor_sensor),
        ]:
            if not value:
                missing.append(name)
        if missing:
            self.log_h(
                f"Nedostaje konfiguracija: {', '.join(missing)}", level="ERROR"
            )
            self.system_enabled = False

        self.max_room_temp = float(heating_cfg.get("max_room_temp", 35.0))
        self.min_room_temp = float(heating_cfg.get("min_room_temp", 8.0))
        self.eco_delta = float(heating_cfg.get("eco_delta", 2.0))
        self.initial_targets_applied = False
        self.apply_initial_targets_on_start = bool(
            heating_cfg.get("apply_initial_targets_on_start", False)
        )
        self.eco_state_file = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "eco_state.json")
        )
        self.eco_last_persisted_state = self.load_persisted_eco_state()
        self.eco_startup_synced = False
        self.overheat_prev = self.get_state(self.overheat_switch) == "on"
        self.eco_state_at_overheat_start = self.get_state(self.eco_switch)

        config_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "room_configs.yaml")
        )
        with open(config_path, "r", encoding="utf-8") as f:
            self.room_configs = yaml.safe_load(f) or {}

        self.listen_state(self.eco_changed, self.eco_switch)
        for ent in self.eco_sync_source_switches:
            self.listen_state(self.eco_sync_source_changed, ent)
        self.run_every(self.main_loop, "now", 60)
        self.log_h(f"AI grijanje (glavni) {self.version} pokrenut | sobe: {len(self.room_configs)}")
        self.log_h(
            f"Konfiguracija | aktivni_switch={self.active_switch} | eco_switch={self.eco_switch} | overheat_switch={self.overheat_switch}",
            level="DEBUG",
        )
        if self.eco_sync_source_switches:
            self.log_h(
                f"ECO sync aktivan | izvori={self.eco_sync_source_switches} | mode={self.eco_sync_mode}",
                level="DEBUG",
            )

    def main_loop(self, kwargs):
        """
        Glavna petlja AI grijanja.
        
        Provjerava globalne uvjete (sustav aktivan, overheat), postavlja poÄŤetne ciljeve
        ako je potrebno, i odrĹľava sustav bez mijenjanja ruÄŤnih ciljeva termostata.
        """
        if not self.update_system_enabled():
            self.log_h("Sustav nije aktivan (global stop)", level="DEBUG")
            return

        if self.get_state(self.active_switch) != "on":
            self.log_h("AI grijanje je iskljuceno")
            return


        if self.eco_sync_source_switches:
            self.sync_eco_from_source_switches()

        overheat_now = self.get_state(self.overheat_switch) == "on"
        if overheat_now and not self.overheat_prev:
            self.eco_state_at_overheat_start = self.get_state(self.eco_switch)
            self.log_h(
                f"Ulazak u overheat | eco_na_startu={self.eco_state_at_overheat_start}",
                level="DEBUG",
            )
        if (not overheat_now) and self.overheat_prev:
            self.reconcile_eco_after_overheat()
        self.overheat_prev = overheat_now

        if overheat_now:
            self.log_h("Pregrijavanje aktivno -> Glavni ne mijenja ciljeve")
            return

        if not self.eco_startup_synced:
            self.reconcile_eco_on_startup()
            self.eco_startup_synced = True
        if not self.initial_targets_applied:
            if self.apply_initial_targets_on_start:
                self.apply_initial_targets_once()
                self.log_h("Pocetni ciljevi postavljeni iz room_configs")
            else:
                self.log_h(
                    "Pocetni reset ciljeva je iskljucen -> ostavljam trenutne targete termostata"
                )
            self.initial_targets_applied = True
        else:
            flow = self.get_temp(self.flow_sensor)
            if flow is None:
                self.log_h("Glavni aktivan -> rucni ciljevi termostata ostaju netaknuti")
            else:
                self.log_h(f"Glavni aktivan | polaz {flow:.1f}C -> rucni ciljevi ostaju")
            self.log_h(
                f"Status | senzor_polaza={self.flow_sensor} | polaz={flow}",
                level="DEBUG",
            )

    def eco_changed(self, entity, attribute, old, new, kwargs):
        self.log_h(f"ECO promjena: {old} -> {new}")
        if self.get_state(self.overheat_switch) == "on":
            self.log_h(
                "ECO promjena tijekom overheata -> odgodeno uskladivanje nakon izlaska",
                level="INFO",
            )
            return
        self.persist_eco_state(new)

        for room_name, room_info in self.room_configs.items():
            climate_entity = room_info.get("climate")
            if not climate_entity:
                continue

            current_target = self.as_float(
                self.get_state(climate_entity, attribute="temperature"),
                fallback=None,
            )
            if current_target is None:
                self.log_h(f"ECO: ne mogu procitati cilj za {room_name}")
                continue

            if new == "on":
                new_target = current_target - self.eco_delta
            else:
                new_target = current_target + self.eco_delta

            new_target = self.clamp(new_target)
            self.log_h(
                f"ECO racun | soba={room_name} | trenutni={current_target:.1f} | novi={new_target:.1f}",
                level="DEBUG",
            )
            self.log_h(
                f"ECO: {room_name} -> {new_target:.1f}C (delta={self.eco_delta:+.1f})",
                level="DEBUG",
            )
            self.call_service(
                "climate/set_temperature",
                entity_id=climate_entity,
                temperature=round(new_target, 1),
            )
            self.log_h(f"{room_name}: ECO cilj -> {new_target:.1f}C")

    def eco_sync_source_changed(self, entity, attribute, old, new, kwargs):
        self.log_h(
            f"ECO sync izvor promjena | {entity}: {old} -> {new}",
            level="DEBUG",
        )
        self.sync_eco_from_source_switches()

    def sync_eco_from_source_switches(self):
        if not self.eco_switch or not self.eco_sync_source_switches:
            return

        states = [self.get_state(ent) == "on" for ent in self.eco_sync_source_switches]
        if not states:
            return

        if self.eco_sync_mode == "all_on":
            desired_on = all(states)
        else:
            desired_on = any(states)

        eco_on = self.get_state(self.eco_switch) == "on"
        if desired_on == eco_on:
            return

        service = "input_boolean/turn_on" if desired_on else "input_boolean/turn_off"
        self.call_service(service, entity_id=self.eco_switch)
        self.log_h(
            f"ECO sync primijenjen | eco -> {'ON' if desired_on else 'OFF'}",
            level="INFO",
        )

    def reconcile_eco_after_overheat(self):
        start_eco_on = str(self.eco_state_at_overheat_start).lower() == "on"
        end_eco_on = self.get_state(self.eco_switch) == "on"

        if start_eco_on == end_eco_on:
            self.log_h(
                "Izlazak iz overheata | ECO stanje nepromijenjeno -> bez uskladivanja",
                level="DEBUG",
            )
            return

        delta = -self.eco_delta if end_eco_on else self.eco_delta
        self.log_h(
            f"Izlazak iz overheata | ECO promjena tijekom overheata -> uskladivanje delta={delta:+.1f}C",
            level="INFO",
        )

        for room_name, room_info in self.room_configs.items():
            climate_entity = room_info.get("climate")
            if not climate_entity:
                continue

            current_target = self.as_float(
                self.get_state(climate_entity, attribute="temperature"),
                fallback=None,
            )
            if current_target is None:
                continue

            new_target = self.clamp(current_target + delta)
            self.call_service(
                "climate/set_temperature",
                entity_id=climate_entity,
                temperature=round(new_target, 1),
            )
            self.log_h(
                f"ECO post-overheat | {room_name}: {current_target:.1f} -> {new_target:.1f}",
                level="DEBUG",
            )
        self.persist_eco_state("on" if end_eco_on else "off")

    def reconcile_eco_on_startup(self):
        current_eco = self.get_state(self.eco_switch)
        if current_eco not in ("on", "off"):
            return

        if self.eco_last_persisted_state in ("on", "off") and self.eco_last_persisted_state != current_eco:
            delta = -self.eco_delta if current_eco == "on" else self.eco_delta
            self.log_h(
                f"Startup ECO sync | persisted={self.eco_last_persisted_state} -> current={current_eco} | delta={delta:+.1f}C",
                level="INFO",
            )
            for room_name, room_info in self.room_configs.items():
                climate_entity = room_info.get("climate")
                if not climate_entity:
                    continue
                current_target = self.as_float(
                    self.get_state(climate_entity, attribute="temperature"),
                    fallback=None,
                )
                if current_target is None:
                    continue
                new_target = self.clamp(current_target + delta)
                self.call_service(
                    "climate/set_temperature",
                    entity_id=climate_entity,
                    temperature=round(new_target, 1),
                )
                self.log_h(
                    f"ECO startup-sync | {room_name}: {current_target:.1f} -> {new_target:.1f}",
                    level="DEBUG",
                )

        self.persist_eco_state(current_eco)

    def load_persisted_eco_state(self):
        try:
            with open(self.eco_state_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            state = data.get("eco_state")
            if state in ("on", "off"):
                return state
        except Exception:
            return None
        return None

    def persist_eco_state(self, state):
        if state not in ("on", "off"):
            return
        try:
            with open(self.eco_state_file, "w", encoding="utf-8") as f:
                json.dump({"eco_state": state}, f, ensure_ascii=True)
            self.eco_last_persisted_state = state
        except Exception:
            return

    def apply_initial_targets_once(self):
        for room_name, room_info in self.room_configs.items():
            climate_entity = room_info.get("climate")
            if not climate_entity:
                self.log_h(f"Soba {room_name} nema termostat entitet")
                continue

            base_target = self.as_float(room_info.get("target"), fallback=21.0)
            base_target = self.clamp(base_target)
            self.log_h(
                f"Pocetni cilj | soba={room_name} | cilj={base_target:.1f}",
                level="DEBUG",
            )
            self.call_service(
                "climate/set_temperature",
                entity_id=climate_entity,
                temperature=round(base_target, 1),
            )
            self.log_h(f"{room_name}: pocetni cilj -> {base_target:.1f}C")

    def update_system_enabled(self):
        boiler_temp = self.get_temp(self.boiler_sensor)
        outdoor_temp = self.get_outdoor_temp_avg()
        self.log_h(
            f"Provjera sustava | kotao={boiler_temp} | vanjska={outdoor_temp}",
            level="DEBUG",
        )

        if boiler_temp is None or outdoor_temp is None:
            return self.system_enabled

        if boiler_temp < 35.0 or outdoor_temp > 21.0:
            if self.system_enabled:
                self.log_h(
                    f"Sustav pauziran | kotao {boiler_temp:.1f}C | vanjska {outdoor_temp:.1f}C"
                )
            self.system_enabled = False
            return False

        if boiler_temp > 40.0 and outdoor_temp <= 20.0:
            if not self.system_enabled:
                self.log_h(
                    f"Sustav aktiviran | kotao {boiler_temp:.1f}C | vanjska {outdoor_temp:.1f}C"
                )
            self.system_enabled = True
            return True

        return self.system_enabled

    def clamp(self, value):
        value = min(value, self.max_room_temp)
        value = max(value, self.min_room_temp)
        return value

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

    def as_float(self, value, fallback=None):
        try:
            if value in (None, "unknown", "unavailable"):
                return fallback
            return float(value)
        except Exception:
            return fallback

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[GRIJANJE] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

