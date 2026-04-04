#
# Samostalni kontroler pumpe V2.6 (global stop conditions)
# Pali pumpu ako bilo koja soba treba grijanje
# Uvjet: hladna pec OFF i kotao >= 40C i vanjska <= 20C
# Overheat ima prioritet i drzi pumpu ON
# Dodano: minimalni ON/OFF interval protiv cikanja releja
# Histereza: stop kad kotao <35 ili vanjska >21
# Logovi: samo greske
#

import os
from datetime import datetime
import time
from ai_kuca.core.base_app import BaseApp
from ai_kuca.core.logger import push_log_to_ha


class AIPump(BaseApp):
    """
    Klasa za kontrolu pumpe grijanja.
    
    Upravlja ukljuÄŤivanjem/iskljuÄŤivanjem pumpe na temelju potreba soba,
    temperature kotla i vanjske temperature, s histerezom i minimalnim intervalima.
    """
    def initialize(self):
        self.init_base()
        system_cfg = self.load_system_config()
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "pump", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))
        self.version = "V2." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        self.log_h(f"AI pumpa {self.version} pokrenuta", level="INFO")
        """
        Inicijalizira AIPump skriptu.
        
        UÄŤitava konfiguraciju senzora i postavlja minimalne intervale,
        te pokreÄ‡e petlju kontrole svakih 30 sekundi.
        """
        system_cfg = self.load_system_config()
        heating_cfg = system_cfg.get("heating_main", {})
        pump_cfg = system_cfg.get("pump", {})

        self.overheat_switch = pump_cfg.get("overheat_switch")
        self.pump_switch = pump_cfg.get("pump_switch")
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
            ("pump.overheat_switch", self.overheat_switch),
            ("pump.pump_switch", self.pump_switch),
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
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "pump", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.min_on_seconds = int(pump_cfg.get("min_on_seconds", 120))
        self.min_off_seconds = int(pump_cfg.get("min_off_seconds", 120))
        self.main_loop_interval = int(pump_cfg.get("main_loop_interval", 15))
        self.last_pump_change_ts = time.time()

        self.room_configs = self.load_yaml_file("room_configs.yaml")

        self.run_every(self.pump_loop, "now", self.main_loop_interval)
        self.log_h(f"AI pumpa {self.version} pokrenuta | sobe: {len(self.room_configs)}")
        self.log_h(
            f"Konfiguracija | min_on={self.min_on_seconds}s | min_off={self.min_off_seconds}s | interval={self.main_loop_interval}s",
            level="DEBUG",
        )

    def pump_loop(self, kwargs):
        if not self.update_system_enabled():
            self.log_h("Sustav pauziran (global stop) -> pumpa iskljucena", level="DEBUG")
            self.ensure_pump(False)
            return

        overheat = self.get_state(self.overheat_switch) == "on"

        if overheat:
            self.log_h("Pregrijavanje aktivno -> pumpa ukljucena (ignorira se min_off_seconds)", level="DEBUG")
            self.ensure_pump(True, ignore_min_interval=True)
            return

        need_heat = False
        for room_info in self.room_configs.values():
            climate_entity = room_info.get("climate")
            if not climate_entity:
                continue

            current_temp = self.as_float(self.get_state(climate_entity, attribute="current_temperature"))
            target_temp = self.as_float(self.get_state(climate_entity, attribute="temperature"))
            if current_temp is None or target_temp is None:
                continue

            self.log_h(
                f"Provjera sobe | {climate_entity} | trenutna={current_temp:.2f} | cilj={target_temp:.2f}",
                level="DEBUG",
            )

            if target_temp > current_temp:
                need_heat = True
                self.log_h(f"Soba {climate_entity} treba grijanje | {current_temp:.1f} < {target_temp:.1f}", level="DEBUG")
                break

        self.ensure_pump(need_heat)
        self.log_h(f"Zakljucak | treba_grijanje={need_heat}", level="DEBUG")

    def update_system_enabled(self):
        boiler_temp = self.get_temp(self.boiler_sensor)
        outdoor_temp = self.get_outdoor_temp_avg()

        if boiler_temp is None or outdoor_temp is None:
            self.ensure_required_sensors(
                {
                    "boiler_sensor": self.boiler_sensor,
                    "outdoor_sensor": self.outdoor_sensor,
                },
                module_name="AIPump",
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

    def ensure_pump(self, desired_on, ignore_min_interval=False):
        """
        Osigurava stanje pumpe prema Ĺľeljenom stanju.
        
        S minimalnim intervalima keĹˇenja (min_off_seconds, min_on_seconds)
        da bi se izbjeglo ÄŤeste prebacivanje releja.
        Kada je ignore_min_interval=True (pri overheat-u), minimalni interval se ignora.
        
        Args:
            desired_on (bool): Trebaju li pumpa biti ukljuÄŤena (True) ili iskljuÄŤena (False).
            ignore_min_interval (bool): Ako je True, ignora minimalne intervale (koristi se za overheat).
        """
        pump_state = self.get_state(self.pump_switch)
        now = time.time()
        elapsed = now - self.last_pump_change_ts

        if desired_on and pump_state != "on":
            if elapsed < self.min_off_seconds and not ignore_min_interval:
                remaining = self.min_off_seconds - elapsed
                self.log_h(
                    f"Pokusaj ukljucivanja blokiran | min_off={self.min_off_seconds}s | proslih={elapsed:.0f}s | do_pokusa={remaining:.0f}s",
                    level="DEBUG",
                )
                return
            if ignore_min_interval and elapsed < self.min_off_seconds:
                self.log_h(
                    f"Pokusaj ukljucivanja FORSIRAN (overheat prioritet) | min_off={self.min_off_seconds}s | proslih={elapsed:.0f}s",
                    level="DEBUG",
                )
            elif not ignore_min_interval:
                self.log_h(
                    f"Pokusaj ukljucivanja dozvoljeno | min_off={self.min_off_seconds}s | proslih={elapsed:.0f}s",
                    level="DEBUG",
                )
            self.call_service("switch/turn_on", entity_id=self.pump_switch)
            self.last_pump_change_ts = now
            self.log_h("Pumpa ukljucena")

        elif not desired_on and pump_state == "on":
            if elapsed < self.min_on_seconds and not ignore_min_interval:
                remaining = self.min_on_seconds - elapsed
                self.log_h(
                    f"Pokusaj iskljucivanja blokiran | min_on={self.min_on_seconds}s | proslih={elapsed:.0f}s | do_pokusa={remaining:.0f}s",
                    level="DEBUG",
                )
                return
            if ignore_min_interval and elapsed < self.min_on_seconds:
                self.log_h(
                    f"Pokusaj iskljucivanja FORSIRAN (overheat prioritet) | min_on={self.min_on_seconds}s | proslih={elapsed:.0f}s",
                    level="DEBUG",
                )
            elif not ignore_min_interval:
                self.log_h(
                    f"Pokusaj iskljucivanja dozvoljeno | min_on={self.min_on_seconds}s | proslih={elapsed:.0f}s",
                    level="DEBUG",
                )
            self.call_service("switch/turn_off", entity_id=self.pump_switch)
            self.last_pump_change_ts = now
            self.log_h("Pumpa iskljucena")

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

    def as_float(self, value):
        try:
            if value in (None, "unknown", "unavailable"):
                return None
            return float(value)
        except Exception:
            return None

    def log_h(self, message, level="INFO"):
        push_log_to_ha(self, message, level, self.log_sensor_entity, self.log_history_seconds, self.log_max_items)
        if not self.should_log(level):
            return
        self.log(f"[PUMPA GRIJANJA] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

