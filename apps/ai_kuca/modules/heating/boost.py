import os
from datetime import datetime
import yaml
import appdaemon.plugins.hass.hassapi as hass
from ai_kuca.core.logger import push_log_to_ha


class AIBoost(hass.Hass):
    """
    Klasa za boost grijanja odabrane sobe.
    
    PoveÄ‡ava ciljnu temperaturu sobe za odabrano vrijeme,
    koristeÄ‡i boost razinu i trajanje iz input_select-a.
    """
    def initialize(self):
        """
        Inicijalizira AIBoost skriptu.
        
        UÄŤitava konfiguraciju boost opcija i soba, te sluĹˇa promjene
        na boost_select i duration_select entitetima.
        """
        self.version = "V2." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        system_cfg = self.load_system_config()
        boost_cfg = system_cfg.get("boost", {})
        heating_cfg = system_cfg.get("heating_main", {})
        self.log_level = system_cfg.get("logging_level", "INFO")
        log_cfg = system_cfg.get("ai_kuca_log", {})
        log_map = system_cfg.get("ai_kuca_log_sensors", {})
        self.log_sensor_entity = log_map.get(
            "boost", log_cfg.get("sensor_entity", "sensor.ai_kuca_log")
        )
        self.log_history_seconds = int(log_cfg.get("history_seconds", 120))
        self.log_max_items = int(log_cfg.get("max_items", 50))

        self.boost_select = boost_cfg.get("boost_select")
        self.duration_select = boost_cfg.get("duration_select")

        self.boiler_sensor = heating_cfg.get("boiler_sensor")
        self.outdoor_sensor = heating_cfg.get("outdoor_sensor")
        self.outdoor_temp_sensors = heating_cfg.get("outdoor_temp_sensors") or []
        if isinstance(self.outdoor_temp_sensors, str):
            self.outdoor_temp_sensors = [self.outdoor_temp_sensors]
        if not isinstance(self.outdoor_temp_sensors, list):
            self.outdoor_temp_sensors = []
        self.flow_target = boost_cfg.get("flow_target")
        self.flow_target_input = boost_cfg.get("flow_target_input")

        self.system_enabled = True
        missing = []
        for name, value in [
            ("boost.boost_select", self.boost_select),
            ("boost.duration_select", self.duration_select),
            ("boost.flow_target", self.flow_target),
            ("boost.flow_target_input", self.flow_target_input),
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

        config_file = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "room_configs.yaml")
        )
        with open(config_file, "r", encoding="utf-8") as f:
            self.rooms = yaml.safe_load(f) or {}

        self.previous_targets = {}
        self.timer = None

        self.sync_input_select_options()
        self.listen_state(self.start_boost, self.boost_select)
        self.log_h(f"AI boost {self.version} spreman | sobe: {len(self.rooms)}")
        self.log_h(
            f"Konfiguracija | izbor_boost={self.boost_select} | trajanje_boost={self.duration_select}",
            level="DEBUG",
        )

    def sync_input_select_options(self):
        system_cfg = self.load_system_config()
        boost_cfg = system_cfg.get("boost", {}) or {}

        duration_map = boost_cfg.get("duration_options", {}) or {}
        room_groups = boost_cfg.get("room_groups", {}) or {}

        room_names = []
        for room_name, room_cfg in (self.rooms or {}).items():
            if isinstance(room_cfg, dict) and room_cfg.get("climate"):
                room_names.append(str(room_name))

        boost_options = ["NONE", "sve"]
        for group_name in room_groups.keys():
            if isinstance(group_name, str) and group_name:
                boost_options.append(group_name)
        for room_name in room_names:
            if room_name not in boost_options:
                boost_options.append(room_name)
        # HA input_select ne dozvoljava duplikate opcija.
        boost_options = list(dict.fromkeys(boost_options))

        duration_options = [str(k) for k in duration_map.keys() if str(k).strip()]
        if not duration_options:
            duration_options = ["15 minuta"]

        self._set_input_select_options(self.boost_select, boost_options, "BOOST sobe/grupe")
        self._set_input_select_options(self.duration_select, duration_options, "BOOST trajanja")

    def _set_input_select_options(self, entity_id, options, label):
        if not entity_id:
            return
        if self.get_state(entity_id) is None:
            self.log_h(f"{label}: entitet nije dostupan ({entity_id})", level="WARNING")
            return
        try:
            self.call_service(
                "input_select/set_options",
                entity_id=entity_id,
                options=options,
            )
            current = self.get_state(entity_id)
            if current not in options and options:
                self.call_service(
                    "input_select/select_option",
                    entity_id=entity_id,
                    option=options[0],
                )
            self.log_h(f"{label}: sinkronizirano opcija={len(options)}", level="INFO")
        except Exception as ex:
            self.log_h(f"{label}: neuspjesna sinkronizacija ({ex})", level="WARNING")

    def start_boost(self, entity, attribute, old, new, kwargs):
        if not self.update_system_enabled():
            self.log_h("Sustav pauziran (global stop) -> BOOST otkazan", level="DEBUG")
            return

        if new in (None, "NONE"):
            self.log_h("BOOST ignoriran (vrijednost NONE)", level="DEBUG")
            return

        selection = str(new).lower()

        # UÄŤitaj duration options iz konfiguracije
        system_cfg = self.load_system_config()
        boost_cfg = system_cfg.get("boost", {})
        duration_map = boost_cfg.get("duration_options", {})
        if not duration_map:
            self.log_h(
                "BOOST: duration_options nije konfiguriran u system_configs.yaml; koristi se 900s", level="WARNING"
            )

        duration_str = self.get_state(self.duration_select)
        boost_seconds = duration_map.get(duration_str, 900)
        self.log_h(
            f"BOOST trajanje | izbor='{duration_str}' | sekunde={boost_seconds}",
            level="DEBUG",
        )

        selected_rooms = self.resolve_selection(selection)
        if not selected_rooms:
            self.log_h(f"BOOST: nema validnih soba za opciju {selection}")
            return

        self.previous_targets = {}
        for climate in selected_rooms:
            temp = self.as_float(self.get_state(climate, attribute="temperature"))
            if temp is not None:
                self.previous_targets[climate] = temp

        boiler_temp = self.get_temp(self.boiler_sensor)
        if boiler_temp is not None:
            flow_target = min(boiler_temp - 5.0, 70.0)
            self.set_flow_target(round(flow_target, 1))
            self.log_h(
                f"BOOST polaz | kotao={boiler_temp:.1f} | cilj={flow_target:.1f}",
                level="DEBUG",
            )

        for climate in selected_rooms:
            self.call_service("climate/set_temperature", entity_id=climate, temperature=35)
            self.log_h(f"BOOST soba {climate} -> 35C", level="DEBUG")

        self.log_h(f"BOOST POCETAK | sobe: {selected_rooms} | trajanje: {boost_seconds / 60:.0f} min")

        if self.timer:
            self.cancel_timer(self.timer)
        self.timer = self.run_in(self.end_boost, boost_seconds)
        self.log_h("BOOST timer postavljen", level="DEBUG")

    def end_boost(self, kwargs):
        for climate, temp in self.previous_targets.items():
            self.call_service("climate/set_temperature", entity_id=climate, temperature=temp)

        self.previous_targets = {}
        self.call_service("input_select/select_option", entity_id=self.boost_select, option="NONE")
        self.log_h("BOOST zavrsen - temperature vracene")

    def resolve_selection(self, selection):
        selected_rooms = []

        # UÄŤitaj room_groups iz konfiguracije
        system_cfg = self.load_system_config()
        boost_cfg = system_cfg.get("boost", {})
        room_groups = boost_cfg.get(
            "room_groups",
            {
                "sve": [],
                "osnovni": ["dnevna", "kupaona", "spavaca", "mali"],
                "pomocni": ["tia", "spajz"]
            }
        )

        if selection == "sve":
            selected_rooms = [cfg.get("climate") for cfg in self.rooms.values() if cfg.get("climate")]
        elif selection in room_groups:
            for room in room_groups[selection]:
                climate = self.rooms.get(room, {}).get("climate")
                if climate:
                    selected_rooms.append(climate)
        elif "+" in selection:
            for room in selection.split("+"):
                room = room.strip()
                climate = self.rooms.get(room, {}).get("climate")
                if climate:
                    selected_rooms.append(climate)
        else:
            climate = self.rooms.get(selection, {}).get("climate")
            if climate:
                selected_rooms.append(climate)

        return selected_rooms

    def set_flow_target(self, value):
        if self.get_state(self.flow_target_input) is not None:
            try:
                self.call_service(
                    "input_number/set_value",
                    entity_id=self.flow_target_input,
                    value=value,
                )
                return
            except Exception as e:
                self.log_h(f"BOOST: neuspjesno postavljanje entiteta input_number ({e})")

        try:
            self.set_state(self.flow_target, state=value)
        except Exception as e:
            self.log_h(f"BOOST: ne mogu postaviti cilj polaza ({e})")

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

    def as_float(self, value):
        try:
            if value in (None, "unknown", "unavailable"):
                return None
            return float(value)
        except Exception:
            return None

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
        self.log(f"[BOOST] {message}", level=level)

    def should_log(self, level):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        cfg = str(getattr(self, "log_level", "INFO")).upper()
        return levels.get(str(level).upper(), 20) >= levels.get(cfg, 20)

