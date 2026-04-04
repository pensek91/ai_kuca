#
# Overheat kontrola za AI Heating V2.8 (global stop conditions)
# - Faza 1: proporcionalno podizanje targeta (bazirano na rucnim targetima)
# - Faza 2: full overheat, target 35C, pumpa ON, ventil FULL OPEN 60s + pauza
# - Histereza: stabilniji prijelazi medu fazama
# - Nakon overheat-a vraca prethodne (rucne) targete
# - Snapshot se cuva u local file (app directory)
#

import os
from datetime import datetime
import json
from ai_kuca.core.base_app import BaseApp
from ai_kuca.core.logger import push_log_to_ha


class AIOverheat(BaseApp):
    """
    Klasa za kontrolu overheat stanja u grijanju.
    
    Upravlja fazama overheat-a na temelju temperature kotla:
    - Faza 0: Normalno stanje
    - Faza 1: Proporcionalno podizanje ciljeva
    - Faza 2: Puni overheat s maksimalnim ciljevima i otvaranjem ventila
    
    Koristi histerezu za stabilne prijelaze i sprema snapshot prethodnih ciljeva.
    """
    def initialize(self):
        self.init_base()
        system_cfg = self.load_system_config()
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "overheat", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))
        self.version = "V2." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        self.log_h(f"AI overheat {self.version} pokrenut", level="INFO")
        """
        Inicijalizira AIOverheat skriptu.
        
        UÄŤitava konfiguraciju, postavlja senzore i entitete, te pokreÄ‡e glavnu petlju.
        TakoÄ‘er uÄŤitava snapshot prethodnih ciljeva iz datoteke ako postoji.
        """
        system_cfg = self.load_system_config()
        overheat_cfg = system_cfg.get("overheat", {})
        heating_cfg = system_cfg.get("heating_main", {})
        pump_cfg = system_cfg.get("pump", {})
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "overheat", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.overheat_switch = overheat_cfg.get("overheat_switch")
        self.valve_pause = overheat_cfg.get("valve_pause")
        self.valve_open = overheat_cfg.get("valve_open")

        self.pump_candidates = pump_cfg.get("pump_candidates") or []
        self.pump_switch = None

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
            ("overheat.overheat_switch", self.overheat_switch),
            ("overheat.valve_pause", self.valve_pause),
            ("overheat.valve_open", self.valve_open),
            ("pump.pump_candidates", self.pump_candidates),
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

        self.main_loop_interval = int(overheat_cfg.get("main_loop_interval", 30))

        # Histereza pragovi
        self.stage1_on = float(overheat_cfg.get("stage1_on", 81.0))
        self.stage1_off = float(overheat_cfg.get("stage1_off", 79.0))
        self.stage2_on = float(overheat_cfg.get("stage2_on", 89.0))
        self.stage2_off = float(overheat_cfg.get("stage2_off", 87.0))

        # 0=normal, 1=proportional overheat, 2=full overheat
        self.mode = 0
        self.pre_overheat_targets = {}
        self.baseline_targets = {}
        self.original_targets = {}
        self.full_open_done = False

        self.rooms = self.load_yaml_file("room_configs.yaml")

        self.snapshot_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "overheat_snapshot.json")
        )
        self.restore_snapshot_from_file()

        self.run_every(self.overheat_loop, "now", self.main_loop_interval)
        self.log_h(f"AI pregrijavanje {self.version} pokrenuto | sobe: {len(self.rooms)}")
        self.log_h(
            f"Konfiguracija | pragovi: {self.stage1_on}/{self.stage1_off}/{self.stage2_on}/{self.stage2_off} | interval={self.main_loop_interval}s",
            level="DEBUG",
        )

    def overheat_loop(self, kwargs):
        if not self.update_system_enabled():
            if self.get_state(self.overheat_switch) == "on":
                self.call_service("input_boolean/turn_off", entity_id=self.overheat_switch)
            if self.get_state(self.valve_pause) == "on":
                self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)
            self.log_h("Sustav pauziran (global stop) -> reset pregrijavanja", level="DEBUG")
            return

        kotao_temp = self.get_kotao_temp()
        if kotao_temp is None:
            self.log_h("Kotao temperatura nedostupna")
            return

        prev_mode = self.mode
        self.log_h(f"Provjera moda | trenutni_mod={prev_mode} | kotao_temp={kotao_temp:.1f}C", level="DEBUG")
        self.mode = self.next_mode(self.mode, kotao_temp)
        if prev_mode != self.mode:
            self.log_h(
                f"Promjena moda | {prev_mode} -> {self.mode} | kotao {kotao_temp:.1f}C",
                level="DEBUG",
            )

        # sigurnosno: ako je overheat prekidac ostao ON (npr. nakon restarta),
        # a mod je 0, ugasi overheat i vrati ciljeve
        if self.mode == 0 and self.get_state(self.overheat_switch) == "on":
            self.call_service("input_boolean/turn_off", entity_id=self.overheat_switch)
            self.log_h("Pregrijavanje iskljuceno (sigurnosni reset) | mod=0")
            self.restore_pre_overheat_targets()
            self.full_open_done = False
            if self.get_state(self.valve_pause) == "on":
                self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)
            return

        if prev_mode == 0 and self.mode in (1, 2):
            self.snapshot_current_targets()
            self.call_service("input_boolean/turn_on", entity_id=self.overheat_switch)
            self.full_open_done = False
            self.log_h(f"Pregrijavanje ukljuceno | kotao {kotao_temp:.1f}C | mod {self.mode}")

        if self.mode == 1:
            delta_c = max(0.0, (kotao_temp - 80.0) * 2.0)
            self.log_h(f"Proporcionalno pregrijavanje | kotao {kotao_temp:.1f}C | +{delta_c:.1f}C")
            self.log_h(f"Faza 1: delta_c = max(0, ({kotao_temp:.1f} - 80) * 2) = {delta_c:.1f}", level="DEBUG")

            for room_name, room_info in self.rooms.items():
                climate_entity = room_info.get("climate")
                if not climate_entity:
                    continue

                base_target = self.baseline_targets.get(climate_entity)
                if base_target is None:
                    base_target = self.as_float(self.get_state(climate_entity, attribute="temperature"), None)
                if base_target is None:
                    continue

                new_target = min(base_target + delta_c, 35.0)
                self.set_climate_if_changed(climate_entity, new_target)
                self.log_h(f"{room_name}: cilj -> {new_target:.1f}C")
                self.log_h(
                    f"Pregrijavanje faza1 | soba={room_name} | baza={base_target:.1f} | novi={new_target:.1f}",
                    level="DEBUG",
                )

            if self.get_state(self.valve_pause) == "on":
                self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)
            return

        if self.mode == 2:
            self.log_h(f"Puno pregrijavanje | kotao {kotao_temp:.1f}C -> svi ciljevi 35C")

            for room_name, room_info in self.rooms.items():
                climate_entity = room_info.get("climate")
                if not climate_entity:
                    continue
                self.set_climate_if_changed(climate_entity, 35.0)

            pump_entity = self.resolve_pump_entity()
            if pump_entity:
                self.log_h(f"Rezolviranja pumpe: {pump_entity}", level="DEBUG")
                if self.get_state(pump_entity) != "on":
                    self.call_service("switch/turn_on", entity_id=pump_entity)
                    self.log_h(f"Pumpa ukljucena (pregrijavanje) | {pump_entity}", level="DEBUG")
                else:
                    self.log_h(f"Pumpa je vec ON | {pump_entity}", level="DEBUG")
            else:
                self.log_h("UPOZORENJE: Nisu pronaÄ‘eni entiteti pumpe za pregrijavanje!", level="WARNING")

            if not self.full_open_done:
                self.full_open_done = True
                self.call_service("input_boolean/turn_on", entity_id=self.valve_pause)
                self.call_service("switch/turn_on", entity_id=self.valve_open)
                self.run_in(self.turn_off_valve_open, 60)

            return

        if prev_mode in (1, 2):
            self.call_service("input_boolean/turn_off", entity_id=self.overheat_switch)
            self.log_h("Pregrijavanje iskljuceno | vracam prethodne ciljeve")
            self.restore_pre_overheat_targets()
            self.full_open_done = False

        if self.get_state(self.valve_pause) == "on":
            self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)

    def turn_off_valve_open(self, kwargs):
        self.call_service("switch/turn_off", entity_id=self.valve_open)

    def next_mode(self, current_mode, kotao_temp):
        """
        OdreÄ‘uje sljedeÄ‡i mod overheat-a na temelju trenutnog moda i temperature kotla.
        
        Koristi histerezu za stabilne prijelaze izmeÄ‘u faza.
        
        Args:
            current_mode (int): Trenutni mod (0=normal, 1=proporcionalni, 2=puni).
            kotao_temp (float): Trenutna temperatura kotla u Â°C.
        
        Returns:
            int: Novi mod (0, 1 ili 2).
        """
        if current_mode == 0:
            if kotao_temp >= self.stage2_on:
                return 2
            if kotao_temp >= self.stage1_on:
                return 1
            return 0

        if current_mode == 1:
            if kotao_temp >= self.stage2_on:
                return 2
            if kotao_temp <= self.stage1_off:
                return 0
            return 1

        if kotao_temp > self.stage2_off:
            return 2
        if kotao_temp >= self.stage1_on:
            return 1
        if kotao_temp <= self.stage1_off:
            return 0
        return 1

    def update_system_enabled(self):
        boiler_temp = self.get_temp(self.boiler_sensor)
        outdoor_temp = self.get_outdoor_temp_avg()
        self.log_h(
            f"Provjera sustava | kotao={boiler_temp} | vanjska={outdoor_temp}",
            level="DEBUG",
        )

        if boiler_temp is None or outdoor_temp is None:
            self.ensure_required_sensors(
                {
                    "boiler_sensor": self.boiler_sensor,
                    "outdoor_sensor": self.outdoor_sensor,
                },
                module_name="AIOverheat",
                cooldown_sec=900,
            )
            self.system_enabled = False
            return False

        if boiler_temp < 35.0 or outdoor_temp > 21.0:
            self.system_enabled = False
            return False

        if boiler_temp > 40.0 and outdoor_temp <= 20.0:
            self.system_enabled = True
            return True

        return self.system_enabled

    def snapshot_current_targets(self):
        self.pre_overheat_targets = {}
        self.baseline_targets = {}
        self.original_targets = {}
        for room_info in self.rooms.values():
            climate_entity = room_info.get("climate")
            temp_sensor = room_info.get("temp_sensor")
            if not climate_entity:
                continue
            # Spremi originalni target s climate uredaja
            orig_target = self.as_float(self.get_state(climate_entity, attribute="temperature"), None)
            if orig_target is not None:
                self.original_targets[climate_entity] = orig_target
            # Postavi baseline na trenutnu temperaturu sobe
            room_temp = self.as_float(self.get_state(temp_sensor), None) if temp_sensor else None
            if room_temp is not None:
                self.baseline_targets[climate_entity] = room_temp
                self.pre_overheat_targets[climate_entity] = room_temp
            elif orig_target is not None:
                # fallback na climate target ako nema temp senzora
                self.baseline_targets[climate_entity] = orig_target
                self.pre_overheat_targets[climate_entity] = orig_target
        self.persist_snapshot_to_file()

    def restore_pre_overheat_targets(self):
        if not self.original_targets:
            return
        for climate_entity, target in self.original_targets.items():
            self.set_climate_if_changed(climate_entity, target)
        self.pre_overheat_targets = {}
        self.baseline_targets = {}
        self.original_targets = {}
        self.persist_snapshot_to_file(clear=True)

    def persist_snapshot_to_file(self, clear=False):
        try:
            if clear:
                if os.path.exists(self.snapshot_path):
                    os.remove(self.snapshot_path)
                return
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(self.pre_overheat_targets, f)
        except Exception as ex:
            self.log_h(
                f"OVERHEAT snapshot write failed | path={self.snapshot_path} | clear={clear} | err={ex}",
                level="WARNING",
            )

    def restore_snapshot_from_file(self):
        if not os.path.exists(self.snapshot_path):
            return
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.pre_overheat_targets = {k: float(v) for k, v in data.items()}
                self.baseline_targets = dict(self.pre_overheat_targets)
        except Exception as ex:
            self.log_h(
                f"OVERHEAT snapshot read failed | path={self.snapshot_path} | err={ex}",
                level="WARNING",
            )
            return

    def get_kotao_temp(self):
        return self.get_temp(self.boiler_sensor)

    def resolve_pump_entity(self):
        if self.pump_switch is not None:
            return self.pump_switch

        for entity in self.pump_candidates:
            state = self.get_state(entity)
            if state is not None:
                self.pump_switch = entity
                self.log_h(f"Entitet pumpe odabran: {entity}")
                return entity

        return None

    def set_climate_if_changed(self, climate_entity, target):
        current = self.as_float(self.get_state(climate_entity, attribute="temperature"), None)
        if current is None or abs(current - target) >= 0.1:
            self.set_climate_target_guarded(
                entity_id=climate_entity,
                temperature=target,
                owner="overheat",
                priority=100,
                ttl_sec=180,
            )

    def get_temp(self, entity):
        try:
            value = self.get_state(entity)
            if value in (None, "unknown", "unavailable"):
                return None
            return float(value)
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

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[OVERHEAT] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

