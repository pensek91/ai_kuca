#
# ValveControl V3.5 (impulse control, no position memory)
# - min impuls = 8s ukljucuje 5s start_delay (realni pomak ~3s)
# - max impuls = 20s
# - kalibracija kada je pumpa OFF >= 30s (zatvaranje 60s)
# - nakon impulsa cekaj 15s prije sljedece provjere
# - global stop conditions (zatvaranje na stop)
#

import os
from datetime import datetime
import time
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class ValveControl(hass.Hass):
    """
    Klasa za kontrolu ventila grijanja pomoÄ‡u impulsa.
    
    Upravlja otvaranjem/zatvaranjem ventila na temelju razlike izmeÄ‘u
    ciljne i stvarne temperature polaza, koristeÄ‡i impulse s pauzama
    i kalibracijom kada je pumpa iskljuÄŤena.
    """
    def initialize(self):
        """
        Inicijalizira ValveControl skriptu.
        
        UÄŤitava konfiguraciju senzora i ventila, postavlja impulse i pauze,
        te pokreÄ‡e petlju kontrole svakih 10 sekundi.
        """
        self.version = "V3." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        system_cfg = self.load_system_config()
        valve_cfg = system_cfg.get("valve_control", {})
        heating_cfg = system_cfg.get("heating_main", {})
        pump_cfg = system_cfg.get("pump", {})
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "valve_control", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.flow_sensor = valve_cfg.get("flow_sensor")
        self.flow_sensor_2 = valve_cfg.get("flow_sensor_2")
        self.target_sensor = valve_cfg.get("target_sensor")

        self.valve_open = valve_cfg.get("valve_open")
        self.valve_close = valve_cfg.get("valve_close")

        self.pump_switch = pump_cfg.get("pump_switch")
        self.overheat_switch = pump_cfg.get("overheat_switch")
        self.valve_pause = valve_cfg.get("valve_pause")
        self.boiler_sensor = valve_cfg.get("boiler_sensor") or heating_cfg.get("boiler_sensor")
        self.outdoor_sensor = valve_cfg.get("outdoor_sensor") or heating_cfg.get("outdoor_sensor")

        self.outdoor_temp_sensors = heating_cfg.get("outdoor_temp_sensors")
        if isinstance(self.outdoor_temp_sensors, str):
            self.outdoor_temp_sensors = [self.outdoor_temp_sensors]
        if not isinstance(self.outdoor_temp_sensors, list):
            self.outdoor_temp_sensors = []

        self.system_enabled = True
        missing = []
        for name, value in [
            ("valve_control.flow_sensor", self.flow_sensor),
            ("valve_control.flow_sensor_2", self.flow_sensor_2),
            ("valve_control.target_sensor", self.target_sensor),
            ("valve_control.valve_open", self.valve_open),
            ("valve_control.valve_close", self.valve_close),
            ("pump.pump_switch", self.pump_switch),
            ("pump.overheat_switch", self.overheat_switch),
            ("valve_control.valve_pause", self.valve_pause),
            ("valve_control.boiler_sensor", self.boiler_sensor),
            ("valve_control.outdoor_sensor", self.outdoor_sensor),
        ]:
            if not value:
                missing.append(name)
        if missing:
            self.log_h(
                f"Nedostaje konfiguracija: {', '.join(missing)}", level="ERROR"
            )
            self.system_enabled = False
        if isinstance(self.outdoor_temp_sensors, str):
            self.outdoor_temp_sensors = [self.outdoor_temp_sensors]
        if not isinstance(self.outdoor_temp_sensors, list):
            self.outdoor_temp_sensors = [self.outdoor_sensor]

        self.start_delay = float(valve_cfg.get("start_delay", 5.0))
        self.deadband = float(valve_cfg.get("deadband", 0.5))

        self.min_base_pulse = float(valve_cfg.get("min_base_pulse", 3.0))
        self.max_base_pulse = float(valve_cfg.get("max_base_pulse", 15.0))
        self.max_error = float(valve_cfg.get("max_error", 10.0))

        self.lock = False
        self.active_relay = None
        self.pump_start_time = None
        self.pump_start_delay = int(valve_cfg.get("pump_start_delay", 25))
        self.pump_off_delay = int(valve_cfg.get("pump_off_delay", 30))
        self.pump_off_timer = None

        self.cooldown_after_pulse = int(valve_cfg.get("cooldown_after_pulse", 15))
        self.cooldown_until = 0

        self.off_calibrated = False
        self.stop_calibrated = False
        self.pause_due_to_hot_c2 = False
        self.pending_pause_due_to_hot_c2 = False

        # --------- SIGURNOSNI RESET RELEJA PRI STARTU ---------
        for relay in [self.valve_open, self.valve_close]:
            if relay:
                self.call_service("switch/turn_off", entity_id=relay)
                self.log_h(f"DEBUG: Sigurnosni reset releja pri startu | gaĹˇenje {relay}", level="DEBUG")
        self.active_relay = None
        # ------------------------------------------------------

        self.run_every(self.control_loop, "now", 15)
        self.log_h(f"AI ventil {self.version} (impuls) pokrenut")
        self.log_h(
            f"Konfiguracija | deadband={self.deadband} | min_pulse={self.min_base_pulse} | max_pulse={self.max_base_pulse}",
            level="DEBUG",
        )

    def control_loop(self, kwargs):
        if not self.enforce_relay_interlock():
            self.lock = False
            self.cooldown_until = time.time() + 2
            return

        if self.lock:
            self.log_h("Preskoci: zakljucano", level="DEBUG")
            return

        if not self.update_system_enabled():
            if not self.stop_calibrated:
                self.stop_calibrated = True
                self.lock = True
                self.log_h("Ventil kalibracija (STOP sustav) | zatvaranje 60s")
                self.activate_relay(self.valve_close, 60)
                self.cooldown_until = time.time() + 60 + self.cooldown_after_pulse
                self.run_in(self.unlock_loop, 60 + 1)
            return
        else:
            self.stop_calibrated = False

        if time.time() < self.cooldown_until:
            self.log_h("Preskoci: odmor nakon impulsa", level="DEBUG")
            return

        pump_state = self.get_state(self.pump_switch)
        if pump_state != "on":
            self.pump_start_time = None
            if self.pump_off_timer is None:
                self.pump_off_timer = self.run_in(self.calibrate_after_pump_off, self.pump_off_delay)
            self.log_h("Pumpa iskljucena -> cekam/kalibriram", level="DEBUG")
            return

        if self.pump_off_timer is not None:
            self.cancel_timer(self.pump_off_timer)
            self.pump_off_timer = None
        self.off_calibrated = False

        if self.pump_start_time is None:
            self.pump_start_time = time.time()
            self.log_h("Pumpa tek ukljucena -> odgoda starta", level="DEBUG")
            return

        if (time.time() - self.pump_start_time) < self.pump_start_delay:
            self.log_h("Preskoci: odgoda starta pumpe", level="DEBUG")
            return

        t_flow = self.get_temp(self.flow_sensor)
        t_flow_2 = self.get_temp(self.flow_sensor_2)
        t_target = self.get_temp(self.target_sensor)

        if t_flow is None or t_target is None:
            self.log_h("Preskoci: nema temperatura (polaz/cilj)", level="DEBUG")
            return

        # ----------- IZMJENA LOGIKE PAUZE zbog C2 > C1 > target -------------
        overheat_active = self.get_state(self.overheat_switch) == "on"
        if not overheat_active and t_flow_2 is not None:
            if t_flow_2 > t_flow and t_flow > t_target:
                if not self.pause_due_to_hot_c2:
                    self.pause_due_to_hot_c2 = True
                    self.lock = True
                    self.pending_pause_due_to_hot_c2 = True
                    self.log_h(
                        f"INFO: Pauza aktivirana zbog C2 > C1 > target | C2={t_flow_2:.1f}, C1={t_flow:.1f}, target={t_target:.1f}",
                        level="INFO",
                    )
                    self.activate_relay(self.valve_close, 60)
                    self.cooldown_until = time.time() + 60 + self.cooldown_after_pulse
                    self.run_in(self.enable_hot_c2_pause, 60 + 1)
                    self.run_in(self.unlock_loop, 60 + 1)
                return
            elif self.pause_due_to_hot_c2 and t_flow < t_target:
                self.pause_due_to_hot_c2 = False
                self.pending_pause_due_to_hot_c2 = False
                self.log_h(
                    f"INFO: Pauza OFF jer C1 < target | C1={t_flow:.1f}, target={t_target:.1f}",
                    level="INFO",
                )
                self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)
        # -------------------------------------------------------------

        if not overheat_active and self.pause_due_to_hot_c2:
            keep_pause = t_flow_2 is not None and (t_flow_2 >= t_flow or t_flow >= (t_target - 1.5))
            if keep_pause and self.get_state(self.valve_pause) != "on":
                self.log_h(
                    f"Pauza hot_c2 prisilno ON | C2={t_flow_2:.1f}C, C1={t_flow:.1f}C, cilj-1.5={t_target - 1.5:.1f}C",
                    level="INFO",
                )
                self.call_service("input_boolean/turn_on", entity_id=self.valve_pause)
            elif (not keep_pause) and self.get_state(self.valve_pause) == "on":
                self.log_h("Pauza hot_c2 ON, ali uvjeti za gasenje su zadovoljeni", level="DEBUG")

        if overheat_active and self.get_state(self.valve_pause) == "on":
            self.pause_due_to_hot_c2 = False
            self.pending_pause_due_to_hot_c2 = False
            self.log_h("Overheat aktivan -> pauza ventila OFF", level="INFO")
            self.call_service("input_boolean/turn_off", entity_id=self.valve_pause)

        if self.get_state(self.valve_pause) == "on":
            self.log_h("Preskoci: ventil pauza", level="DEBUG")
            return

        error = t_target - t_flow
        if abs(error) <= self.deadband:
            self.log_h("Preskoci: mrtva zona", level="DEBUG")
            return

        base_pulse = self.map_error_to_base_pulse(abs(error))
        pulse = base_pulse + self.start_delay
        pulse = max(8.0, min(20.0, pulse))

        relay = self.valve_open if error > 0 else self.valve_close

        self.log_h(
            f"Racun impulsa | error={error:.1f}C | base_pulse={base_pulse:.1f}s | pulse={pulse:.1f}s | relay={'otvaranje' if relay == self.valve_open else 'zatvaranje'}",
            level="DEBUG",
        )
        self.lock = True
        self.log_h(f"Ventil impuls | {'otvaranje' if relay == self.valve_open else 'zatvaranje'} | {pulse:.0f}s")
        # --------- SIGURNOSNI RESET RELEJA ---------
        if self.active_relay:
            self.log_h(f"DEBUG: Sigurnosni reset releja prije impulsa | gaĹˇenje {self.active_relay}", level="DEBUG")
            self.call_service("switch/turn_off", entity_id=self.active_relay)
            self.active_relay = None
        # --------------------------------------------
        self.activate_relay(relay, pulse)
        self.cooldown_until = time.time() + pulse + self.cooldown_after_pulse
        self.run_in(self.unlock_loop, pulse + 1)

    # --- ostatak skripte ostaje identiÄŤan ---
    def map_error_to_base_pulse(self, error):
        if error >= self.max_error:
            return self.max_base_pulse
        ratio = error / self.max_error
        return self.min_base_pulse + (self.max_base_pulse - self.min_base_pulse) * ratio

    def calibrate_after_pump_off(self, kwargs):
        self.pump_off_timer = None
        if self.get_state(self.pump_switch) == "on":
            return
        if self.lock:
            return
        if self.off_calibrated:
            return

        self.lock = True
        self.log_h("Ventil kalibracija (pumpa iskljucena) | zatvaranje 60s")
        self.activate_relay(self.valve_close, 60)
        self.cooldown_until = time.time() + 60 + self.cooldown_after_pulse
        self.off_calibrated = True
        self.run_in(self.unlock_loop, 60 + 1)

    def update_system_enabled(self):
        boiler_temp = self.get_temp(self.boiler_sensor)
        outdoor_temp = self.get_outdoor_temp_avg()

        if boiler_temp is None or outdoor_temp is None:
            return self.system_enabled

        if boiler_temp < 35.0 or outdoor_temp > 21.0:
            self.system_enabled = False
            return False

        if boiler_temp > 40.0 and outdoor_temp <= 20.0:
            self.system_enabled = True
            return True

        return self.system_enabled

    def unlock_loop(self, kwargs):
        self.lock = False

    def enable_hot_c2_pause(self, kwargs):
        if not self.pending_pause_due_to_hot_c2:
            return
        self.pending_pause_due_to_hot_c2 = False
        self.call_service("input_boolean/turn_on", entity_id=self.valve_pause)
        self.log_h("Pauza ventila ON nakon zatvaranja 60s (Krug2 > Krug1)", level="INFO")

    def activate_relay(self, relay, duration):
        # Hard interlock: nikad ne dopusti oba releja ON
        if relay == self.valve_open and self.valve_close:
            self.call_service("switch/turn_off", entity_id=self.valve_close)
        if relay == self.valve_close and self.valve_open:
            self.call_service("switch/turn_off", entity_id=self.valve_open)

        if self.active_relay and self.active_relay != relay:
            self.call_service("switch/turn_off", entity_id=self.active_relay)

        self.active_relay = relay
        self.call_service("switch/turn_on", entity_id=relay)
        self.run_in(self.turn_off_relay, duration, relay=relay)

    def turn_off_relay(self, kwargs):
        relay = kwargs["relay"]
        self.call_service("switch/turn_off", entity_id=relay)
        if self.active_relay == relay:
            self.active_relay = None

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

    def enforce_relay_interlock(self):
        if not self.valve_open or not self.valve_close:
            return True
        open_on = self.get_state(self.valve_open) == "on"
        close_on = self.get_state(self.valve_close) == "on"
        if open_on and close_on:
            self.log_h(
                "INTERLOCK: oba releja ventila su ON -> gasim oba radi zastite",
                level="WARNING",
            )
            self.call_service("switch/turn_off", entity_id=self.valve_open)
            self.call_service("switch/turn_off", entity_id=self.valve_close)
            self.active_relay = None
            return False
        return True

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
        self.log(f"[VENTIL] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)
