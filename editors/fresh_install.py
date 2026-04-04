
import json
import os
import sys
import urllib.error
import urllib.request
import subprocess
from pathlib import Path
import yaml

# --- NOVO: automatska detekcija root foldera projekta ---
def find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / '.env').exists() and (cur / 'apps').is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError('Nije pronađen root folder projekta (mora sadržavati .env i apps/)')

ROOT = find_project_root(Path(__file__).parent)
APPS_YAML = ROOT / "apps" / "apps.yaml"
SYSTEM_YAML = ROOT / "apps" / "ai_kuca" / "config" / "system_configs.yaml"
ROOMS_YAML = ROOT / "apps" / "ai_kuca" / "config" / "room_configs.yaml"
ENV_FILE = ROOT / ".env"
APPDAEMON_YAML = ROOT / "appdaemon.yaml"
DOCKER_COMPOSE_YAML = ROOT / "docker-compose.yaml"
REQUIRED_CODE_FILES = [
    ROOT / "apps" / "ai_kuca" / "modules" / "heating" / "main.py",
    ROOT / "apps" / "ai_kuca" / "modules" / "heating" / "valve.py",
    ROOT / "apps" / "ai_kuca" / "modules" / "ventilation" / "main.py",
]


APP_DEFS = {
    "ai_config_validator": {
        "module": "ai_kuca.modules.config.validator",
        "class": "AIConfigValidator",
    },
    "ai_heating_main": {
        "module": "ai_kuca.modules.heating.main",
        "class": "AIHeatingMain",
    },
    "ai_overheat": {
        "module": "ai_kuca.modules.heating.overheat",
        "class": "AIOverheat",
    },
    "valve_control": {
        "module": "ai_kuca.modules.heating.valve",
        "class": "ValveControl",
    },
    "ai_pump": {
        "module": "ai_kuca.modules.heating.pump",
        "class": "AIPump",
    },
    "ai_boost": {
        "module": "ai_kuca.modules.heating.boost",
        "class": "AIBoost",
    },
    "predictive_sensors": {
        "module": "ai_kuca.modules.predictive.temperature",
        "class": "PredictiveSensors",
    },
    "predictive_humidity": {
        "module": "ai_kuca.modules.predictive.humidity",
        "class": "PredictiveHumidity",
    },
    "ai_ventilation_main": {
        "module": "ai_kuca.modules.ventilation.main",
        "class": "AIVentilacijaMain",
    },
    "ai_kuca_status": {
        "module": "ai_kuca.modules.system.status",
        "class": "AIKucaStatus",
    },
}


def load_yaml(path: Path):
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def save_system_yaml_with_comments(path: Path, data):
    try:
        from system_editor import save_system_yaml_with_comments as _save_with_comments
        _save_with_comments(path, data)
    except Exception:
        save_yaml(path, data)


def load_env(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def save_env(path: Path, values: dict):
    lines = [
        f"HA_URL={values['HA_URL']}",
        f"HA_KEY={values['HA_KEY']}",
        f"LOG_LEVEL={values['LOG_LEVEL']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bootstrap_files():
    (ROOT / "apps" / "ai_kuca" / "config").mkdir(parents=True, exist_ok=True)

    if not APPDAEMON_YAML.exists():
        APPDAEMON_YAML.write_text(
            (
                "appdaemon:\n"
                "  latitude: 45.8150\n"
                "  longitude: 15.9819\n"
                "  elevation: 120\n"
                "  time_zone: \"Europe/Zagreb\"\n\n"
                "  plugins:\n"
                "    HASS:\n"
                "      type: hass\n"
                "      ha_url: !env_var HA_URL\n"
                "      token: !env_var HA_KEY\n"
            ),
            encoding="utf-8",
        )

    if not DOCKER_COMPOSE_YAML.exists():
        DOCKER_COMPOSE_YAML.write_text(
            (
                "services:\n"
                "  appdaemon:\n"
                "    image: acockburn/appdaemon:4.4.2\n"
                "    container_name: appdaemon\n"
                "    restart: unless-stopped\n\n"
                "    env_file:\n"
                "      - .env\n\n"
                "    volumes:\n"
                "      - ./apps:/conf/apps\n"
                "      - ./appdaemon.yaml:/conf/appdaemon.yaml\n\n"
                "      - ./conf/ai_logs:/conf/ai_logs\n"
                "      - ./conf/dashboards:/conf/dashboards\n"
                "      - ./conf/namespaces:/conf/namespaces\n\n"
                "    ports:\n"
                "      - \"5050:5050\"\n"
            ),
            encoding="utf-8",
        )

    if not SYSTEM_YAML.exists():
        save_yaml(
            SYSTEM_YAML,
            {
                "logging_level": "INFO",
                "ai_kuca_log": {
                    "sensor_entity": "sensor.ai_kuca_log",
                    "history_seconds": 120,
                    "max_items": 50,
                },
                "ai_kuca_status": {"check_delay_sec": 8, "app_names": []},
            },
        )

    if not ROOMS_YAML.exists():
        save_yaml(ROOMS_YAML, {})


def ensure_codebase_present():
    missing = [str(p) for p in REQUIRED_CODE_FILES if not p.exists()]
    if not missing:
        return
    print("\nGreska: nedostaju AI_KUCA modul skripte.")
    print("fresh_install.py konfigurira postojeci codebase, ali ga ne instalira samostalno.")
    print("Prvo pokreni full installer:")
    print(f"  python {ROOT / 'full_installer.py'} --target {ROOT} --force")
    print("\nNedostaje:")
    for path in missing:
        print(f"- {path}")
    sys.exit(1)


def prompt_env_setup():
    load_env(ENV_FILE)
    print("\n--- .env setup (obavezno) ---")
    current_url = os.getenv("HA_URL", "")
    current_key = os.getenv("HA_KEY", "")
    current_level = os.getenv("LOG_LEVEL", "info")

    while True:
        url = input(f"HA_URL [{current_url or 'http://homeassistant.local:8123'}]: ").strip()
        if not url:
            url = current_url or "http://homeassistant.local:8123"
        if url.startswith("http://") or url.startswith("https://"):
            break
        print("HA_URL mora počinjati s http:// ili https://")

    while True:
        key = input(f"HA_KEY [{('***' if current_key else '')}]: ").strip()
        if not key:
            key = current_key
        if key:
            break
        print("HA_KEY je obavezan.")

    level = input(f"LOG_LEVEL [{current_level}]: ").strip().lower() or current_level
    if level not in ("debug", "info", "warning", "error", "critical"):
        level = "info"

    values = {"HA_URL": url, "HA_KEY": key, "LOG_LEVEL": level}
    save_env(ENV_FILE, values)
    os.environ.update(values)
    print(f".env spremljen: {ENV_FILE}")


class HAClient:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self.entity_ids = set()

    def load_entities(self):
        req = urllib.request.Request(
            f"{self.url}/api/states",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ids = set()
        for item in payload:
            entity_id = item.get("entity_id")
            if isinstance(entity_id, str) and "." in entity_id:
                ids.add(entity_id)
        self.entity_ids = ids

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.entity_ids


def ask_yes_no(question: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{question} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes", "da", "d"):
            return True
        if raw in ("n", "no", "ne"):
            return False
        print("Neispravan unos. Upiši y ili n.")


def ask_text(label: str, required: bool = True) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value or not required:
            return value
        print("Ovo polje je obavezno.")


def ask_target_step(label: str, default: float = 0.5) -> float:
    while True:
        raw = ask_text(f"{label} (0.5 ili 1.0)", required=False)
        if not raw:
            return float(default)
        try:
            value = float(raw)
        except ValueError:
            print("Neispravan broj.")
            continue
        if value in (0.5, 1.0):
            return value
        print("Dozvoljeno je samo 0.5 ili 1.0.")


def ask_float(label: str, default: float) -> float:
    while True:
        raw = ask_text(f"{label} [{default}]", required=False)
        if not raw:
            return float(default)
        try:
            return float(raw)
        except ValueError:
            print("Neispravan broj.")


def _domain_entities(client: HAClient | None, domain: str):
    if not client or not client.entity_ids:
        return []
    prefix = f"{domain}."
    return sorted([e for e in client.entity_ids if e.startswith(prefix)])


def _select_from_list(label: str, options, allow_empty: bool = False):
    page_size = 25
    filtered = list(options)
    page = 0

    while True:
        if not filtered:
            print("\nNema entiteta za prikaz (nakon filtera).")
        else:
            total_pages = (len(filtered) - 1) // page_size + 1
            page = max(0, min(page, total_pages - 1))
            start = page * page_size
            end = min(start + page_size, len(filtered))
            print(f"\n{label} | prikaz {start + 1}-{end} od {len(filtered)} (stranica {page + 1}/{total_pages})")
            for idx in range(start, end):
                print(f"  {idx + 1:4d}) {filtered[idx]}")

        print("Komande: broj=odabir, n=sljedeća, p=prethodna, f=filter, r=reset filter, m=ručni unos, x=preskoči")
        cmd = input("Odabir: ").strip()
        if not cmd:
            if allow_empty:
                return None
            continue
        if cmd.lower() == "n":
            page += 1
            continue
        if cmd.lower() == "p":
            page -= 1
            continue
        if cmd.lower() == "f":
            q = input("Filter tekst: ").strip().lower()
            filtered = [e for e in options if q in e.lower()] if q else list(options)
            page = 0
            continue
        if cmd.lower() == "r":
            filtered = list(options)
            page = 0
            continue
        if cmd.lower() == "m":
            return None
        if cmd.lower() == "x":
            return None
        try:
            num = int(cmd)
            if 1 <= num <= len(filtered):
                return filtered[num - 1]
            print("Broj je izvan raspona.")
        except ValueError:
            print("Neispravan unos.")


def ask_entity(label: str, domain: str, client: HAClient | None, required: bool = True) -> str:
    options = _domain_entities(client, domain)
    if options:
        picked = _select_from_list(f"{label} ({domain}.*)", options, allow_empty=not required)
        if picked:
            return picked

    while True:
        value = ask_text(f"{label} ({domain}.*)", required=required)

        if not value and not required:
            return value
        if "." not in value:
            print("Entity mora biti u formatu domain.entity_name")
            continue
        if not value.startswith(f"{domain}."):
            print(f"Entity mora počinjati s '{domain}.'")
            continue
        if client and client.entity_ids and not client.exists(value):
            print("Entity ne postoji u Home Assistantu. Pokušaj ponovno.")
            continue
        return value


def normalize_room_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def post_setup_menu():
    while True:
        print("\n--- Sto dalje? ---")
        print("1) Pokreni postavljanje cijelog sustava (Install Wizard)")
        print("2) Pokreni postavljanje soba (Room Editor)")
        print("3) Pokreni postavljanje osnovnih entiteta (System Editor)")
        print("4) AppDaemon kontrola (reload/restart)")
        print("0) Izlaz")
        choice = input("Odabir: ").strip()
        if choice == "0":
            return
        if choice == "1":
            subprocess.run([sys.executable, str(ROOT / "editors" / "fresh_install.py")], cwd=str(ROOT), check=False)
            return
        if choice == "2":
            subprocess.run([sys.executable, str(ROOT / "editors" / "room_editor.py")], cwd=str(ROOT), check=False)
            return
        if choice == "3":
            subprocess.run([sys.executable, str(ROOT / "editors" / "system_editor.py")], cwd=str(ROOT), check=False)
            return
        if choice == "4":
            subprocess.run([sys.executable, str(ROOT / "editors" / "appdaemon_control.py")], cwd=str(ROOT), check=False)
            continue
        print("Neispravan odabir.")


def build_apps_config(enabled_apps):
    out = {}
    for app_name in enabled_apps:
        app_def = APP_DEFS[app_name]
        out[app_name] = {
            "module": app_def["module"],
            "class": app_def["class"],
            "namespace": "default",
        }
    return out


def main():
    print("\nAI_KUCA Interactive Install Wizard\n")
    ensure_codebase_present()
    bootstrap_files()
    prompt_env_setup()

    client = None
    ha_url = os.getenv("HA_URL")
    ha_key = os.getenv("HA_KEY")
    if ha_url and ha_key and ask_yes_no("Želiš validirati entitete direktno iz Home Assistanta?", True):
        try:
            client = HAClient(ha_url, ha_key)
            client.load_entities()
            print(f"HA povezan. Učitano entiteta: {len(client.entity_ids)}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as ex:
            print(f"Upozorenje: HA provjera nije dostupna ({ex}). Nastavljam bez online validacije.")
            client = None

    use_validator = ask_yes_no("Uključiti Config Validator app?", True)
    use_heating = ask_yes_no("Uključiti GRIJANJE module?", True)
    use_boost = use_heating and ask_yes_no("Uključiti BOOST modul?", True)
    use_predictive_temp = ask_yes_no("Uključiti PREDIKCIJU TEMPERATURE?", False)
    use_predictive_humidity = ask_yes_no("Uključiti PREDIKCIJU VLAGE?", False)
    use_ventilation = ask_yes_no("Uključiti VENTILACIJU?", False)
    use_status = ask_yes_no("Uključiti status checker (AIKucaStatus)?", True)

    enabled_apps = []
    if use_validator:
        enabled_apps.append("ai_config_validator")
    if use_heating:
        enabled_apps.extend(["ai_heating_main", "ai_overheat", "valve_control", "ai_pump"])
        if use_boost:
            enabled_apps.append("ai_boost")
    if use_predictive_temp:
        enabled_apps.append("predictive_sensors")
    if use_predictive_humidity:
        enabled_apps.append("predictive_humidity")
    if use_ventilation:
        enabled_apps.append("ai_ventilation_main")
    if use_status:
        enabled_apps.append("ai_kuca_status")

    if not enabled_apps:
        print("Nije odabran niti jedan modul. Prekid.")
        sys.exit(1)

    system_cfg = load_yaml(SYSTEM_YAML)
    rooms_cfg = load_yaml(ROOMS_YAML)

    print("\n--- Obavezne globalne postavke ---")
    if use_heating:
        heating = system_cfg.get("heating_main", {}) or {}
        heating["active_switch"] = ask_entity("Grijanje - glavni prekidač", "input_boolean", client)
        heating["eco_switch"] = ask_entity("Grijanje - ECO prekidač", "input_boolean", client)
        heating["overheat_switch"] = ask_entity("Grijanje - overheat prekidač", "input_boolean", client)
        heating["flow_sensor"] = ask_entity("Grijanje - senzor polaza (krug 1)", "sensor", client)
        heating["boiler_sensor"] = ask_entity("Grijanje - senzor temperature kotla", "sensor", client)
        heating["outdoor_sensor"] = ask_entity("Grijanje - vanjski senzor temperature #1 (primarni)", "sensor", client)
        outdoor_sensor_2 = ask_entity(
            "Grijanje - vanjski senzor temperature #2 (opcionalno)",
            "sensor",
            client,
            required=False,
        )
        outdoor_list = [heating["outdoor_sensor"]]
        if outdoor_sensor_2 and outdoor_sensor_2 not in outdoor_list:
            outdoor_list.append(outdoor_sensor_2)
        heating["outdoor_temp_sensors"] = outdoor_list
        system_cfg["heating_main"] = heating

        overheat = system_cfg.get("overheat", {}) or {}
        overheat["overheat_switch"] = heating["overheat_switch"]
        overheat["valve_pause"] = ask_entity("Overheat - pauza ventila", "input_boolean", client)
        overheat["valve_open"] = ask_entity("Overheat - relej otvaranja ventila", "switch", client)
        system_cfg["overheat"] = overheat

        valve = system_cfg.get("valve_control", {}) or {}
        valve["flow_sensor"] = heating["flow_sensor"]
        valve["flow_sensor_2"] = ask_entity("Ventil - senzor polaza (krug 2)", "sensor", client)
        valve["target_sensor"] = ask_entity("Ventil - ciljni senzor temperature polaza", "sensor", client)
        valve["valve_open"] = overheat["valve_open"]
        valve["valve_close"] = ask_entity("Ventil - relej zatvaranja", "switch", client)
        valve["valve_pause"] = overheat["valve_pause"]
        valve["boiler_sensor"] = heating["boiler_sensor"]
        valve["outdoor_sensor"] = heating["outdoor_sensor"]
        system_cfg["valve_control"] = valve

        pump = system_cfg.get("pump", {}) or {}
        pump["pump_switch"] = ask_entity("Pumpa - glavni prekidač", "switch", client)
        pump["overheat_switch"] = heating["overheat_switch"]
        pump["pump_candidates"] = [pump["pump_switch"]]
        system_cfg["pump"] = pump

        if use_boost:
            boost = system_cfg.get("boost", {}) or {}
            boost["boost_select"] = ask_entity("Boost - odabir sobe", "input_select", client)
            boost["duration_select"] = ask_entity("Boost - odabir trajanja", "input_select", client)
            boost["flow_target"] = ask_entity("Boost - senzor ciljane temperature polaza", "sensor", client)
            boost["flow_target_input"] = ask_entity("Boost - unos ciljne temperature polaza", "input_number", client)
            boost.setdefault("duration_options", {"15 minuta": 900, "30 minuta": 1800, "60 minuta": 3600})
            system_cfg["boost"] = boost

    if use_predictive_temp:
        predictive = system_cfg.get("predictive", {}) or {}
        predictive["forecast_entity"] = ask_entity("Predikcija temperature - vremenska prognoza", "weather", client)
        if use_heating:
            predictive["pump_switch"] = system_cfg.get("pump", {}).get("pump_switch")
            predictive["outdoor_temp_sensors"] = system_cfg.get("heating_main", {}).get("outdoor_temp_sensors", [])
        else:
            predictive["pump_switch"] = ask_entity("Predikcija temperature - prekidač pumpe", "switch", client)
            predictive["outdoor_temp_sensors"] = [ask_entity("Predikcija temperature - vanjski temperaturni senzor", "sensor", client)]
        system_cfg["predictive"] = predictive

    if use_predictive_humidity:
        predictive_h = system_cfg.get("predictive_humidity", {}) or {}
        predictive_h.setdefault("interval_sec", 60)
        predictive_h.setdefault("history_window_minutes", 120)
        predictive_h.setdefault("min_points", 5)
        predictive_h.setdefault("trend_epsilon", 0.2)
        system_cfg["predictive_humidity"] = predictive_h

    if use_ventilation:
        vent = system_cfg.get("ventilation", {}) or {}
        vent["outdoor_humidity_sensor"] = ask_entity("Ventilacija - vanjski senzor vlage", "sensor", client)
        vent["forecast_entity"] = ask_entity("Ventilacija - vremenska prognoza (opcionalno)", "weather", client, required=False)
        if not vent["forecast_entity"]:
            vent.pop("forecast_entity", None)
        system_cfg["ventilation"] = vent

    print("\n--- Konfiguracija soba ---")
    room_count = 0
    while room_count <= 0:
        raw = ask_text("Koliko soba želiš konfigurirati (broj > 0)", required=True)
        try:
            room_count = int(raw)
        except ValueError:
            room_count = 0

    new_rooms = {}
    for idx in range(room_count):
        print(f"\nSoba {idx + 1}/{room_count}")
        room_name = normalize_room_name(ask_text("Naziv sobe (npr. spavaca)", required=True))
        room = {}
        if use_heating:
            room["climate"] = ask_entity(
                f"{room_name} - klima/radijator entitet (opcionalno)",
                "climate",
                client,
                required=False,
            )
            raw_target = ask_text(
                f"{room_name} - ciljana temperatura (opcionalno, npr. 21.0)",
                required=False,
            )
            if raw_target:
                try:
                    room["target"] = float(raw_target)
                except ValueError:
                    room["target"] = 21.0
            room["target_step"] = ask_target_step(
                f"{room_name} - korak target temperature",
                default=0.5,
            )
            if use_predictive_temp and room.get("climate"):
                room_pred = dict(room.get("predictive", {}) or {})
                room_pred["auto_apply_targets"] = ask_yes_no(
                    f"{room_name} - dozvoliti auto predikciju targeta za ovu sobu?",
                    True,
                )
                if ask_yes_no(f"{room_name} - zelis napredne limite auto predikcije po sobi?", False):
                    room_pred["deadband"] = ask_float(
                        f"{room_name} - deadband auto predikcije (C)",
                        0.2,
                    )
                    room_pred["max_step_per_cycle"] = ask_float(
                        f"{room_name} - max promjena po ciklusu (C)",
                        0.5,
                    )
                    room_pred["min_temp"] = ask_float(
                        f"{room_name} - minimalni auto target (C)",
                        8.0,
                    )
                    room_pred["max_temp"] = ask_float(
                        f"{room_name} - maksimalni auto target (C)",
                        35.0,
                    )
                room["predictive"] = room_pred

        if use_predictive_temp:
            room["temp_sensor"] = ask_entity(f"{room_name} - temperaturni senzor (opcionalno)", "sensor", client, required=False)

        if use_predictive_humidity or use_ventilation:
            room["humidity_sensor"] = ask_entity(
                f"{room_name} - senzor vlage (opcionalno; potrebno za vlagu/ventilaciju)",
                "sensor",
                client,
                required=False,
            )

        if use_ventilation:
            fan_entity = ask_entity(f"{room_name} - ventilator (opcionalno)", "fan", client, required=False)
            if fan_entity:
                room["fan"] = fan_entity

        window_raw = ask_text(f"{room_name} - senzori prozora/vrata (zarezom, opcionalno)", required=False)
        if window_raw:
            windows = [w.strip() for w in window_raw.split(",") if w.strip()]
            room["window_sensors"] = windows

        new_rooms[room_name] = room

    if ask_yes_no("Prebrisati postojeći room_configs.yaml novom konfiguracijom?", True):
        rooms_cfg = new_rooms
    else:
        rooms_cfg.update(new_rooms)

    apps_cfg = build_apps_config(enabled_apps)
    if use_status:
        status_cfg = system_cfg.get("ai_kuca_status", {}) or {}
        status_cfg["app_names"] = [a for a in enabled_apps if a != "ai_kuca_status"]
        status_cfg.setdefault("check_delay_sec", 8)
        system_cfg["ai_kuca_status"] = status_cfg

    system_cfg.setdefault("logging_level", "INFO")
    system_cfg.setdefault(
        "ai_kuca_log",
        {"sensor_entity": "sensor.ai_kuca_log", "history_seconds": 120, "max_items": 50},
    )

    save_yaml(APPS_YAML, apps_cfg)
    save_system_yaml_with_comments(SYSTEM_YAML, system_cfg)
    save_yaml(ROOMS_YAML, rooms_cfg)

    print("\nInstalacija/konfiguracija završena.")
    print(f"- apps: {APPS_YAML}")
    print(f"- system config: {SYSTEM_YAML}")
    print(f"- room config: {ROOMS_YAML}")
    print("\nSljedeći korak: restart/reload AppDaemon.")


if __name__ == "__main__":
    main()
    post_setup_menu()
