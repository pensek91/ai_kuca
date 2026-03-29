import yaml
import subprocess
import sys
import os
import json
import urllib.error
import urllib.request
from pathlib import Path

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
SYSTEM_YAML = ROOT / "apps" / "ai_kuca" / "config" / "system_configs.yaml"
ENV_FILE = ROOT / ".env"


def load_yaml(path: Path):
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def _domain_entities(client: HAClient | None, domain: str):
    if not client or not client.entity_ids:
        return []
    prefix = f"{domain}."
    return sorted([e for e in client.entity_ids if e.startswith(prefix)])


def _select_from_list(label: str, options, current_value: str = ""):
    page_size = 25
    filtered = list(options)
    page = 0

    while True:
        if filtered:
            total_pages = (len(filtered) - 1) // page_size + 1
            page = max(0, min(page, total_pages - 1))
            start = page * page_size
            end = min(start + page_size, len(filtered))
            print(f"\n{label} | prikaz {start + 1}-{end} od {len(filtered)} (stranica {page + 1}/{total_pages})")
            for idx in range(start, end):
                print(f"  {idx + 1:4d}) {filtered[idx]}")
        else:
            print("\nNema entiteta za prikaz (nakon filtera).")

        keep = f", Enter=zadrzi [{current_value}]" if current_value else ""
        print(f"Komande: broj=odabir, n=sljedeca, p=prethodna, f=filter, r=reset, m=rucni unos, x=preskoci{keep}")
        cmd = input("Odabir: ").strip()
        if not cmd and current_value:
            return current_value
        if not cmd:
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
            return ""
        try:
            num = int(cmd)
            if 1 <= num <= len(filtered):
                return filtered[num - 1]
            print("Broj je izvan raspona.")
        except ValueError:
            print("Neispravan unos.")


def ask_entity(label: str, domain: str, current: str = "", client: HAClient | None = None, allow_clear: bool = True):
    options = _domain_entities(client, domain)
    if options:
        picked = _select_from_list(f"{label} ({domain}.*)", options, current_value=current)
        if picked is not None:
            return picked

    suffix = f" [{current}]" if current else ""
    raw = input(f"{label}{suffix} (Enter=zadrzi{', -=obrisi' if allow_clear else ''}): ").strip()
    if not raw:
        return current
    if allow_clear and raw == "-":
        return ""
    return raw


def ask_entity_list(label: str, domain: str, current_list, client: HAClient | None = None):
    current_list = current_list or []
    current = ", ".join(str(x) for x in current_list)
    options = _domain_entities(client, domain)
    if options:
        print(f"\n{label} ({domain}.*)")
        print("Unesi vise entiteta odvojeno zarezom.")
        print(f"Dostupno ukupno: {len(options)} entiteta. (Upisi 'l' za kratki pregled)")

    raw = input(f"{label} [{current}] (Enter=zadrzi, -=obrisi sve): ").strip()
    if not raw:
        return current_list
    if raw == "-":
        return []
    if raw.lower() == "l" and options:
        preview = options[:40]
        print("\n--- Kratki pregled entiteta ---")
        for ent in preview:
            print(f"- {ent}")
        if len(options) > len(preview):
            print(f"... i jos {len(options) - len(preview)}")
        raw = input("Upisi entitete (zarezom): ").strip()
        if not raw:
            return current_list
        if raw == "-":
            return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def ask_text(label: str, current: str = "", allow_clear: bool = True) -> str:
    suffix = f" [{current}]" if current else ""
    raw = input(f"{label}{suffix} (Enter=zadrzi{', -=obrisi' if allow_clear else ''}): ").strip()
    if not raw:
        return current
    if allow_clear and raw == "-":
        return ""
    return raw


def ask_float(label: str, current):
    cur = "" if current is None else str(current)
    while True:
        raw = input(f"{label} [{cur}] (Enter=zadrzi): ").strip()
        if not raw:
            return current
        try:
            return float(raw)
        except ValueError:
            print("Neispravan broj.")


def ask_int(label: str, current):
    cur = "" if current is None else str(current)
    while True:
        raw = input(f"{label} [{cur}] (Enter=zadrzi): ").strip()
        if not raw:
            return current
        try:
            return int(raw)
        except ValueError:
            print("Neispravan cijeli broj.")


def ask_list(label: str, current_list):
    current_list = current_list or []
    current = ", ".join(str(x) for x in current_list)
    raw = input(f"{label} [{current}] (Enter=zadrzi, -=obrisi sve): ").strip()
    if not raw:
        return current_list
    if raw == "-":
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def ask_duration_options(current_map):
    data = dict(current_map or {})
    while True:
        print("\n--- Boost trajanja (duration_options) ---")
        if data:
            for idx, (name, seconds) in enumerate(data.items(), start=1):
                print(f"{idx:2d}) {name} = {seconds}s")
        else:
            print("(nema definiranih trajanja)")

        print("1) Dodaj trajanje")
        print("2) Uredi postojece trajanje")
        print("3) Obrisi trajanje")
        print("0) Povratak")
        choice = input("Odabir: ").strip()

        if choice == "0":
            return data
        if choice == "1":
            name = input("Naziv opcije (npr. 45 minuta): ").strip()
            if not name:
                print("Naziv je obavezan.")
                continue
            seconds = ask_int("Vrijednost u sekundama", 900)
            data[name] = int(seconds)
            continue
        if choice == "2":
            if not data:
                print("Nema stavki za urediti.")
                continue
            key = input("Naziv opcije za urediti: ").strip()
            if key not in data:
                print("Opcija ne postoji.")
                continue
            new_name = input(f"Novi naziv [{key}] (Enter=zadrzi): ").strip() or key
            new_seconds = ask_int("Nova vrijednost u sekundama", int(data[key]))
            if new_name != key:
                del data[key]
            data[new_name] = int(new_seconds)
            continue
        if choice == "3":
            if not data:
                print("Nema stavki za brisanje.")
                continue
            key = input("Naziv opcije za brisanje: ").strip()
            if key in data:
                del data[key]
            else:
                print("Opcija ne postoji.")
            continue
        print("Neispravan odabir.")


def ask_room_groups(current_map):
    data = dict(current_map or {})
    while True:
        print("\n--- Boost grupe soba (room_groups) ---")
        if data:
            for idx, (group, rooms) in enumerate(data.items(), start=1):
                room_list = ", ".join(str(r) for r in (rooms or []))
                print(f"{idx:2d}) {group}: [{room_list}]")
        else:
            print("(nema definiranih grupa)")

        print("1) Dodaj grupu")
        print("2) Uredi grupu")
        print("3) Obrisi grupu")
        print("0) Povratak")
        choice = input("Odabir: ").strip()

        if choice == "0":
            return data
        if choice == "1":
            group = input("Naziv grupe (npr. kat, kupaonice): ").strip().lower()
            if not group:
                print("Naziv grupe je obavezan.")
                continue
            raw_rooms = input("Sobe (zarezom, npr. dnevna,kupaona): ").strip()
            rooms = [x.strip() for x in raw_rooms.split(",") if x.strip()] if raw_rooms else []
            data[group] = rooms
            continue
        if choice == "2":
            if not data:
                print("Nema grupa za urediti.")
                continue
            group = input("Naziv grupe za urediti: ").strip().lower()
            if group not in data:
                print("Grupa ne postoji.")
                continue
            current_rooms = ", ".join(str(r) for r in (data.get(group) or []))
            new_group = input(f"Novi naziv grupe [{group}] (Enter=zadrzi): ").strip().lower() or group
            raw_rooms = input(f"Sobe [{current_rooms}] (zarezom, Enter=zadrzi): ").strip()
            if raw_rooms:
                new_rooms = [x.strip() for x in raw_rooms.split(",") if x.strip()]
            else:
                new_rooms = list(data.get(group) or [])
            if new_group != group:
                del data[group]
            data[new_group] = new_rooms
            continue
        if choice == "3":
            if not data:
                print("Nema grupa za brisanje.")
                continue
            group = input("Naziv grupe za brisanje: ").strip().lower()
            if group in data:
                del data[group]
            else:
                print("Grupa ne postoji.")
            continue
        print("Neispravan odabir.")


def _dump_value_block(key: str, value, indent: int = 2):
    block = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True).rstrip().splitlines()
    return [(" " * indent) + line for line in block]


def _section_with_comments(section_name: str, section_data: dict, comments: dict):
    lines = [f"{section_name}:"]
    for key, value in (section_data or {}).items():
        comment = comments.get(key)
        if comment:
            lines.append(f"  # {comment}")
        lines.extend(_dump_value_block(key, value, indent=2))
    return lines


def render_system_config_with_comments(cfg: dict):
    lines = []
    lines.append("# AI_KUCA - system konfiguracija")
    lines.append("# Komentari su opis polja na jednostavnom jeziku.")
    lines.append("")
    lines.append("# Globalna razina logiranja (DEBUG/INFO/WARNING/ERROR/CRITICAL)")
    lines.extend(_dump_value_block("logging_level", cfg.get("logging_level", "INFO"), indent=0))
    lines.append("")

    log_comments = {
        "sensor_entity": "HA entitet u koji se zapisuje centralni log",
        "history_seconds": "Koliko sekundi povijesti log poruka cuvamo",
        "max_items": "Maksimalan broj log zapisa u povijesti",
    }
    lines.append("# Postavke centralnog log senzora")
    lines.extend(_section_with_comments("ai_kuca_log", cfg.get("ai_kuca_log", {}), log_comments))
    lines.append("")

    heating_comments = {
        "active_switch": "Glavni prekidac grijanja (ON/OFF)",
        "eco_switch": "ECO prekidac grijanja",
        "overheat_switch": "Prekidac koji oznacava overheat stanje",
        "flow_sensor": "Senzor polazne temperature (krug 1)",
        "boiler_sensor": "Senzor temperature kotla",
        "outdoor_sensor": "Primarni vanjski senzor temperature (#1)",
        "outdoor_temp_sensors": "Lista vanjskih senzora za prosjek/fallback (#1, #2, ...)",
        "max_room_temp": "Maksimalna dozvoljena ciljna temperatura sobe",
        "min_room_temp": "Minimalna dozvoljena ciljna temperatura sobe",
        "eco_delta": "Koliko stupnjeva ECO mod smanjuje ciljnu temperaturu",
        "eco_sync_source_switches": "Lista prekidaca koji automatski sinkroniziraju ECO (npr. laku_noc)",
        "eco_sync_mode": "Nacin sinkronizacije ECO iz izvora: any_on ili all_on",
    }
    lines.append("# Glavne postavke grijanja")
    lines.extend(_section_with_comments("heating_main", cfg.get("heating_main", {}), heating_comments))
    lines.append("")

    overheat_comments = {
        "overheat_switch": "Prekidac overheat stanja",
        "valve_pause": "Prekidac pauze ventila",
        "valve_open": "Relej za otvaranje ventila",
        "pump_candidates": "Lista kandidata za pumpu (fallback)",
        "boiler_sensor": "Senzor temperature kotla",
        "outdoor_sensor": "Senzor vanjske temperature",
        "main_loop_interval": "Interval glavne petlje overheat logike (sek)",
        "stage1_on": "Prag ukljucenja overheat faze 1",
        "stage1_off": "Prag iskljucenja overheat faze 1",
        "stage2_on": "Prag ukljucenja overheat faze 2",
        "stage2_off": "Prag iskljucenja overheat faze 2",
    }
    lines.append("# Overheat zastita")
    lines.extend(_section_with_comments("overheat", cfg.get("overheat", {}), overheat_comments))
    lines.append("")

    valve_comments = {
        "flow_sensor": "Senzor polaza (krug 1)",
        "flow_sensor_2": "Senzor polaza (krug 2)",
        "target_sensor": "Senzor ciljane temperature polaza",
        "valve_open": "Relej otvaranja ventila",
        "valve_close": "Relej zatvaranja ventila",
        "pump_switch": "Prekidac pumpe grijanja",
        "valve_pause": "Prekidac pauze ventila",
        "boiler_sensor": "Senzor temperature kotla",
        "outdoor_sensor": "Senzor vanjske temperature",
        "start_delay": "Odgoda prije stvarnog pomaka ventila (sek)",
        "deadband": "Mrtva zona regulacije (bez reakcije)",
        "min_base_pulse": "Minimalno trajanje impulsa ventila (sek)",
        "max_base_pulse": "Maksimalno trajanje impulsa ventila (sek)",
        "max_error": "Maksimalna greska koja ulazi u izracun impulsa",
        "pump_start_delay": "Odgoda paljenja pumpe prije regulacije ventila (sek)",
        "pump_off_delay": "Odgoda nakon gasenja pumpe prije kalibracije (sek)",
        "cooldown_after_pulse": "Pauza nakon impulsa ventila (sek)",
    }
    lines.append("# Kontrola ventila")
    lines.extend(_section_with_comments("valve_control", cfg.get("valve_control", {}), valve_comments))
    lines.append("")

    pump_comments = {
        "pump_switch": "Glavni prekidac pumpe",
        "overheat_switch": "Overheat prekidac (prioritet sigurnosti)",
        "pump_candidates": "Lista kandidata prekidaca pumpe (fallback)",
        "min_on_seconds": "Minimalno vrijeme rada pumpe (sek)",
        "min_off_seconds": "Minimalno vrijeme mirovanja pumpe (sek)",
        "main_loop_interval": "Interval provjere stanja pumpe (sek)",
    }
    lines.append("# Postavke pumpe")
    lines.extend(_section_with_comments("pump", cfg.get("pump", {}), pump_comments))
    lines.append("")

    boost_comments = {
        "flow_target": "Senzor preporucene ciljne temperature polaza",
        "flow_target_input": "Input broj za zadavanje ciljne temperature polaza",
        "boost_select": "Input select za odabir sobe/grupe boosta",
        "duration_select": "Input select za odabir trajanja boosta",
        "duration_options": "Mapa opcija trajanja boosta u sekundama",
        "room_groups": "Preddefinirane grupe soba za boost",
    }
    lines.append("# Boost postavke")
    lines.extend(_section_with_comments("boost", cfg.get("boost", {}), boost_comments))
    lines.append("")

    pred_comments = {
        "outdoor_temp_sensors": "Lista vanjskih temperaturnih senzora",
        "forecast_entity": "Weather entitet za prognozu temperature",
        "pump_switch": "Prekidac pumpe (koristi se u predikciji)",
        "window_short_minutes": "Kratki prozor povijesti (minute)",
        "window_long_minutes": "Dugi prozor povijesti (minute)",
        "min_points_short": "Minimalno tocaka za kratki trend",
        "min_points_long": "Minimalno tocaka za dugi trend",
        "loss_coeff_default": "Default koeficijent toplinskog gubitka",
        "window_loss_multiplier": "Multiplikator gubitka kad je prozor otvoren",
        "weight_short": "Tezina kratkog trenda",
        "weight_long": "Tezina dugog trenda",
        "recommended_target_max_adjust": "Maksimalna korekcija preporucenog targeta (C)",
        "auto_apply_targets": "Automatski primijeni preporuceni target na climate (true/false)",
        "auto_apply_deadband": "Mrtva zona promjene targeta (C) za auto-apply",
        "auto_apply_max_step_per_cycle": "Maksimalna promjena targeta po ciklusu (C)",
        "auto_apply_skip_when_overheat": "Ako je overheat aktivan, preskoci auto-apply (true/false)",
    }
    lines.append("# Predikcija temperature")
    lines.extend(_section_with_comments("predictive", cfg.get("predictive", {}), pred_comments))
    lines.append("")

    pred_h_comments = {
        "interval_sec": "Interval racunanja predikcije vlage (sek)",
        "history_window_minutes": "Duljina povijesti za predikciju vlage (minute)",
        "min_points": "Minimalan broj tocki za racun predikcije vlage",
        "trend_epsilon": "Prag osjetljivosti za oznaku trenda vlage",
    }
    lines.append("# Predikcija vlage")
    lines.extend(_section_with_comments("predictive_humidity", cfg.get("predictive_humidity", {}), pred_h_comments))
    lines.append("")

    vent_comments = {
        "outdoor_humidity_sensor": "Senzor vanjske vlage",
        "forecast_entity": "Weather entitet za fallback prognozu vlage",
        "interval_sec": "Interval provjere ventilacije (sek)",
        "min_samples": "Minimalan broj uzoraka prije baseline logike",
        "baseline_window_minutes": "Prozor baseline vlage (minute)",
        "delta_on": "Koliko iznad baseline vlage ukljucujemo ventilaciju",
        "delta_off": "Koliko iznad baseline vlage gasimo ventilaciju",
        "abs_on": "Apsolutni prag vlage za ukljucivanje ventilacije (%)",
        "abs_off": "Apsolutni prag vlage za iskljucivanje ventilacije (%)",
        "min_on_sec": "Minimalno vrijeme rada ventilacije (sek)",
        "min_off_sec": "Minimalna pauza izmedu dva paljenja (sek)",
        "outdoor_humidity_max": "Maksimalna dozvoljena vanjska vlaga za ventilaciju (%)",
        "allow_if_outdoor_unknown": "Ako nema vanjske vlage, dopusti ventilaciju (true/false)",
        "window_pause": "Ako je prozor otvoren, pauziraj ventilaciju (true/false)",
        "pause_switches": "Lista globalnih prekidaca koji pauziraju ventilaciju",
    }
    lines.append("# Ventilacija")
    lines.extend(_section_with_comments("ventilation", cfg.get("ventilation", {}), vent_comments))
    lines.append("")

    status_comments = {
        "check_delay_sec": "Koliko cekati prije status provjere nakon pokretanja (sek)",
        "app_names": "Popis appova koji trebaju biti dostupni",
    }
    lines.append("# Status checker")
    lines.extend(_section_with_comments("ai_kuca_status", cfg.get("ai_kuca_status", {}), status_comments))
    lines.append("")

    return "\n".join(lines) + "\n"


def save_system_yaml_with_comments(path: Path, cfg: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_system_config_with_comments(cfg), encoding="utf-8")


def preview_system(cfg: dict):
    print("\n--- Pregled system_configs.yaml ---")
    print(render_system_config_with_comments(cfg))


def post_setup_menu():
    while True:
        print("\n--- Sto dalje? ---")
        print("1) Pokreni postavljanje soba (Room Editor)")
        print("2) Pokreni postavljanje osnovnih entiteta (System Editor)")
        print("3) Pokreni postavljanje cijelog sustava (Install Wizard)")
        print("4) AppDaemon kontrola (reload/restart)")
        print("0) Izlaz")
        choice = input("Odabir: ").strip()
        if choice == "0":
            return
        if choice == "1":
            subprocess.run([sys.executable, str(ROOT / "editors" / "room_editor.py")], cwd=str(ROOT), check=False)
            return
        if choice == "2":
            subprocess.run([sys.executable, str(ROOT / "editors" / "system_editor.py")], cwd=str(ROOT), check=False)
            return
        if choice == "3":
            subprocess.run([sys.executable, str(ROOT / "editors" / "fresh_install.py")], cwd=str(ROOT), check=False)
            return
        if choice == "4":
            subprocess.run([sys.executable, str(ROOT / "editors" / "appdaemon_control.py")], cwd=str(ROOT), check=False)
            continue
        print("Neispravan odabir.")


def edit_logging(cfg: dict, client: HAClient | None = None):
    cfg["logging_level"] = ask_text("Logiranje - razina logova", str(cfg.get("logging_level", "INFO")), allow_clear=False).upper()
    log = dict(cfg.get("ai_kuca_log", {}) or {})
    log["sensor_entity"] = ask_entity("Logiranje - HA log senzor", "sensor", current=log.get("sensor_entity", "sensor.ai_kuca_log"), client=client, allow_clear=False)
    log["history_seconds"] = ask_int("Logiranje - trajanje povijesti (sek)", int(log.get("history_seconds", 120)))
    log["max_items"] = ask_int("Logiranje - maksimalan broj zapisa", int(log.get("max_items", 50)))
    cfg["ai_kuca_log"] = log


# Nova funkcija za uređivanje ai_kuca_log_sensors
def edit_log_sensors(cfg: dict):
    sensors = dict(cfg.get("ai_kuca_log_sensors", {}) or {})
    while True:
        print("\n=== LOG SENSORS EDITOR ===")
        if sensors:
            print("Trenutni log senzori:")
            for k, v in sensors.items():
                print(f"  {k}: {v}")
        else:
            print("(nema definiranih log senzora)")
        print("\n1) Dodaj/uredi log senzor")
        print("2) Obrisi log senzor")
        print("0) Povratak")
        choice = input("Odabir: ").strip()
        if choice == "0":
            break
        if choice == "1":
            key = input("Naziv log senzora (npr. heating_main): ").strip()
            if not key:
                print("Naziv je obavezan.")
                continue
            value = input(f"Vrijednost entiteta za '{key}': ").strip()
            if not value:
                print("Vrijednost je obavezna.")
                continue
            sensors[key] = value
            print(f"Spremljeno: {key}: {value}")
            continue
        if choice == "2":
            key = input("Naziv log senzora za brisanje: ").strip()
            if key in sensors:
                del sensors[key]
                print(f"Obrisano: {key}")
            else:
                print("Senzor ne postoji.")
            continue
        print("Neispravan odabir.")
    cfg["ai_kuca_log_sensors"] = sensors


def edit_heating(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("heating_main", {}) or {})
    sec["active_switch"] = ask_entity("Grijanje - glavni prekidac", "input_boolean", current=sec.get("active_switch", ""), client=client, allow_clear=False)
    sec["eco_switch"] = ask_entity("Grijanje - ECO prekidac", "input_boolean", current=sec.get("eco_switch", ""), client=client, allow_clear=False)
    sec["overheat_switch"] = ask_entity("Grijanje - overheat prekidac", "input_boolean", current=sec.get("overheat_switch", ""), client=client, allow_clear=False)
    sec["flow_sensor"] = ask_entity("Grijanje - senzor polaza (krug 1)", "sensor", current=sec.get("flow_sensor", ""), client=client, allow_clear=False)
    sec["boiler_sensor"] = ask_entity("Grijanje - senzor temperature kotla", "sensor", current=sec.get("boiler_sensor", ""), client=client, allow_clear=False)
    sec["outdoor_sensor"] = ask_entity("Grijanje - vanjski senzor temperature #1 (primarni)", "sensor", current=sec.get("outdoor_sensor", ""), client=client, allow_clear=False)
    sec["outdoor_temp_sensors"] = ask_entity_list("Grijanje - vanjski senzori za prosjek/fallback (#1, #2, ...)", "sensor", sec.get("outdoor_temp_sensors", []), client=client)
    sec["max_room_temp"] = ask_float("Grijanje - maksimalna sobna temperatura", sec.get("max_room_temp", 35.0))
    sec["min_room_temp"] = ask_float("Grijanje - minimalna sobna temperatura", sec.get("min_room_temp", 8.0))
    sec["eco_delta"] = ask_float("Grijanje - ECO smanjenje temperature", sec.get("eco_delta", 2.0))
    sec["eco_sync_source_switches"] = ask_entity_list(
        "Grijanje - izvori za ECO sync (input_boolean)",
        "input_boolean",
        sec.get("eco_sync_source_switches", []),
        client=client,
    )
    eco_sync_mode = ask_text(
        "Grijanje - ECO sync mode (any_on/all_on)",
        str(sec.get("eco_sync_mode", "any_on")),
        allow_clear=False,
    ).strip().lower()
    if eco_sync_mode not in ("any_on", "all_on"):
        eco_sync_mode = "any_on"
    sec["eco_sync_mode"] = eco_sync_mode
    cfg["heating_main"] = sec


def edit_overheat(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("overheat", {}) or {})
    sec["overheat_switch"] = ask_entity("Overheat - aktivni prekidac", "input_boolean", current=sec.get("overheat_switch", ""), client=client, allow_clear=False)
    sec["valve_pause"] = ask_entity("Overheat - pauza ventila", "input_boolean", current=sec.get("valve_pause", ""), client=client, allow_clear=False)
    sec["valve_open"] = ask_entity("Overheat - relej otvaranja ventila", "switch", current=sec.get("valve_open", ""), client=client, allow_clear=False)
    sec["pump_candidates"] = ask_entity_list("Overheat - kandidati pumpe", "switch", sec.get("pump_candidates", []), client=client)
    sec["boiler_sensor"] = ask_entity("Overheat - senzor temperature kotla", "sensor", current=sec.get("boiler_sensor", ""), client=client, allow_clear=False)
    sec["outdoor_sensor"] = ask_entity("Overheat - vanjski senzor temperature (referentni)", "sensor", current=sec.get("outdoor_sensor", ""), client=client, allow_clear=False)
    sec["main_loop_interval"] = ask_int("Overheat - interval glavne petlje (sek)", sec.get("main_loop_interval", 30))
    sec["stage1_on"] = ask_float("Overheat - prag faze 1 ukljucenje (C)", sec.get("stage1_on", 81.0))
    sec["stage1_off"] = ask_float("Overheat - prag faze 1 iskljucenje (C)", sec.get("stage1_off", 79.0))
    sec["stage2_on"] = ask_float("Overheat - prag faze 2 ukljucenje (C)", sec.get("stage2_on", 89.0))
    sec["stage2_off"] = ask_float("Overheat - prag faze 2 iskljucenje (C)", sec.get("stage2_off", 87.0))
    cfg["overheat"] = sec


def edit_pump(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("pump", {}) or {})
    sec["pump_switch"] = ask_entity("Pumpa - glavni prekidac", "switch", current=sec.get("pump_switch", ""), client=client, allow_clear=False)
    sec["overheat_switch"] = ask_entity("Pumpa - overheat prekidac", "input_boolean", current=sec.get("overheat_switch", ""), client=client, allow_clear=False)
    sec["pump_candidates"] = ask_entity_list("Pumpa - kandidati prekidaca (fallback)", "switch", sec.get("pump_candidates", []), client=client)
    sec["min_on_seconds"] = ask_int("Pumpa - minimalno vrijeme rada (sek)", sec.get("min_on_seconds", 120))
    sec["min_off_seconds"] = ask_int("Pumpa - minimalno vrijeme mirovanja (sek)", sec.get("min_off_seconds", 120))
    sec["main_loop_interval"] = ask_int("Pumpa - interval provjere (sek)", sec.get("main_loop_interval", 15))
    cfg["pump"] = sec


def edit_valve(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("valve_control", {}) or {})
    sec["flow_sensor"] = ask_entity("Ventil - senzor polaza (krug 1)", "sensor", current=sec.get("flow_sensor", ""), client=client, allow_clear=False)
    sec["flow_sensor_2"] = ask_entity("Ventil - senzor polaza (krug 2)", "sensor", current=sec.get("flow_sensor_2", ""), client=client, allow_clear=False)
    sec["target_sensor"] = ask_entity("Ventil - ciljni senzor temperature", "sensor", current=sec.get("target_sensor", ""), client=client, allow_clear=False)
    sec["valve_open"] = ask_entity("Ventil - relej otvaranja", "switch", current=sec.get("valve_open", ""), client=client, allow_clear=False)
    sec["valve_close"] = ask_entity("Ventil - relej zatvaranja", "switch", current=sec.get("valve_close", ""), client=client, allow_clear=False)
    sec["valve_pause"] = ask_entity("Ventil - prekidac pauze", "input_boolean", current=sec.get("valve_pause", ""), client=client, allow_clear=False)
    sec["boiler_sensor"] = ask_entity("Ventil - senzor temperature kotla", "sensor", current=sec.get("boiler_sensor", ""), client=client, allow_clear=False)
    sec["outdoor_sensor"] = ask_entity("Ventil - vanjski senzor temperature (referentni)", "sensor", current=sec.get("outdoor_sensor", ""), client=client, allow_clear=False)
    sec["start_delay"] = ask_float("Ventil - start delay (sek)", sec.get("start_delay", 5.0))
    sec["deadband"] = ask_float("Ventil - deadband", sec.get("deadband", 0.5))
    sec["min_base_pulse"] = ask_float("Ventil - minimalni impuls (sek)", sec.get("min_base_pulse", 3.0))
    sec["max_base_pulse"] = ask_float("Ventil - maksimalni impuls (sek)", sec.get("max_base_pulse", 15.0))
    sec["max_error"] = ask_float("Ventil - maksimalna greska", sec.get("max_error", 10.0))
    sec["pump_start_delay"] = ask_int("Ventil - odgoda nakon starta pumpe (sek)", sec.get("pump_start_delay", 25))
    sec["pump_off_delay"] = ask_int("Ventil - odgoda nakon gasenja pumpe (sek)", sec.get("pump_off_delay", 30))
    sec["cooldown_after_pulse"] = ask_int("Ventil - cooldown nakon impulsa (sek)", sec.get("cooldown_after_pulse", 15))
    cfg["valve_control"] = sec


def edit_boost(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("boost", {}) or {})
    while True:
        print("\n=== BOOST EDITOR ===")
        print("1) Entitet: ciljni flow senzor")
        print("2) Entitet: input broj za flow cilj")
        print("3) Entitet: input_select za sobe/grupe")
        print("4) Entitet: input_select za trajanje")
        print("5) Uredi trajanja (duration_options)")
        print("6) Uredi grupe soba (room_groups)")
        print("7) Brzi pregled boost konfiguracije")
        print("0) Povratak")

        choice = input("Odabir: ").strip()
        if choice == "0":
            break
        if choice == "1":
            sec["flow_target"] = ask_entity(
                "Boost - ciljni flow senzor",
                "sensor",
                current=sec.get("flow_target", ""),
                client=client,
                allow_clear=False,
            )
            continue
        if choice == "2":
            sec["flow_target_input"] = ask_entity(
                "Boost - input broj za flow cilj",
                "input_number",
                current=sec.get("flow_target_input", ""),
                client=client,
                allow_clear=False,
            )
            continue
        if choice == "3":
            sec["boost_select"] = ask_entity(
                "Boost - odabir sobe/grupe",
                "input_select",
                current=sec.get("boost_select", ""),
                client=client,
                allow_clear=False,
            )
            continue
        if choice == "4":
            sec["duration_select"] = ask_entity(
                "Boost - odabir trajanja",
                "input_select",
                current=sec.get("duration_select", ""),
                client=client,
                allow_clear=False,
            )
            continue
        if choice == "5":
            sec["duration_options"] = ask_duration_options(sec.get("duration_options", {}))
            continue
        if choice == "6":
            sec["room_groups"] = ask_room_groups(sec.get("room_groups", {}))
            continue
        if choice == "7":
            print("\n--- Trenutni BOOST ---")
            print(yaml.safe_dump({"boost": sec}, sort_keys=False, allow_unicode=True))
            continue
        print("Neispravan odabir.")

    sec["duration_options"] = dict(sec.get("duration_options", {}) or {})
    sec["room_groups"] = dict(sec.get("room_groups", {}) or {})
    cfg["boost"] = sec


def edit_ventilation(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("ventilation", {}) or {})
    sec["outdoor_humidity_sensor"] = ask_entity("Ventilacija - vanjski senzor vlage", "sensor", current=sec.get("outdoor_humidity_sensor", ""), client=client, allow_clear=False)
    sec["forecast_entity"] = ask_entity("Ventilacija - vremenska prognoza (opcionalno)", "weather", current=sec.get("forecast_entity", ""), client=client, allow_clear=True)
    if not sec.get("forecast_entity"):
        sec.pop("forecast_entity", None)
    sec["interval_sec"] = ask_int("Ventilacija - interval provjere (sek)", sec.get("interval_sec", 60))
    sec["min_samples"] = ask_int("Ventilacija - minimalan broj uzoraka", sec.get("min_samples", 30))
    sec["baseline_window_minutes"] = ask_int("Ventilacija - baseline prozor (minute)", sec.get("baseline_window_minutes", 120))
    sec["delta_on"] = ask_float("Ventilacija - ukljuci na +delta vlage", sec.get("delta_on", 8.0))
    sec["delta_off"] = ask_float("Ventilacija - iskljuci na +delta vlage", sec.get("delta_off", 4.0))
    sec["abs_on"] = ask_float("Ventilacija - apsolutni prag ukljucenja (%)", sec.get("abs_on", 70.0))
    sec["abs_off"] = ask_float("Ventilacija - apsolutni prag iskljucenja (%)", sec.get("abs_off", 60.0))
    sec["min_on_sec"] = ask_int("Ventilacija - minimalno vrijeme rada (sek)", sec.get("min_on_sec", 300))
    sec["min_off_sec"] = ask_int("Ventilacija - minimalna pauza (sek)", sec.get("min_off_sec", 180))
    sec["outdoor_humidity_max"] = ask_float("Ventilacija - maksimalna vanjska vlaga (%)", sec.get("outdoor_humidity_max", 80.0))
    sec["pause_switches"] = ask_entity_list("Ventilacija - globalni pauza prekidaci", "input_boolean", sec.get("pause_switches", []), client=client)
    cfg["ventilation"] = sec


def edit_predictive(cfg: dict, client: HAClient | None = None):
    sec = dict(cfg.get("predictive", {}) or {})
    sec["forecast_entity"] = ask_entity("Predikcija temperature - vremenska prognoza", "weather", current=sec.get("forecast_entity", ""), client=client, allow_clear=False)
    sec["pump_switch"] = ask_entity("Predikcija temperature - prekidac pumpe", "switch", current=sec.get("pump_switch", ""), client=client, allow_clear=False)
    sec["outdoor_temp_sensors"] = ask_entity_list("Predikcija temperature - vanjski senzori za prosjek/fallback (#1, #2, ...)", "sensor", sec.get("outdoor_temp_sensors", []), client=client)
    sec["window_short_minutes"] = ask_int("Predikcija temperature - kratki prozor (minute)", sec.get("window_short_minutes", 15))
    sec["window_long_minutes"] = ask_int("Predikcija temperature - dugi prozor (minute)", sec.get("window_long_minutes", 60))
    sec["recommended_target_max_adjust"] = ask_float("Predikcija - maksimalna korekcija preporucenog targeta (C)", sec.get("recommended_target_max_adjust", 2.0))
    auto_apply_current = str(sec.get("auto_apply_targets", False)).lower() in ("1", "true", "on", "yes", "da", "d")
    sec["auto_apply_targets"] = ask_text(
        "Predikcija - automatski primijeni target? (true/false)",
        "true" if auto_apply_current else "false",
        allow_clear=False,
    ).strip().lower() in ("1", "true", "on", "yes", "da", "d")
    sec["auto_apply_deadband"] = ask_float("Predikcija - deadband auto-apply (C)", sec.get("auto_apply_deadband", 0.2))
    sec["auto_apply_max_step_per_cycle"] = ask_float(
        "Predikcija - maksimalna promjena po ciklusu (C)",
        sec.get("auto_apply_max_step_per_cycle", 0.5),
    )
    skip_oh_current = str(sec.get("auto_apply_skip_when_overheat", True)).lower() in ("1", "true", "on", "yes", "da", "d")
    sec["auto_apply_skip_when_overheat"] = ask_text(
        "Predikcija - preskoci auto-apply kad je overheat? (true/false)",
        "true" if skip_oh_current else "false",
        allow_clear=False,
    ).strip().lower() in ("1", "true", "on", "yes", "da", "d")
    cfg["predictive"] = sec


def edit_predictive_humidity(cfg: dict):
    sec = dict(cfg.get("predictive_humidity", {}) or {})
    sec["interval_sec"] = ask_int("Predikcija vlage - interval provjere (sek)", sec.get("interval_sec", 60))
    sec["history_window_minutes"] = ask_int("Predikcija vlage - povijesni prozor (minute)", sec.get("history_window_minutes", 120))
    sec["min_points"] = ask_int("Predikcija vlage - minimalan broj tocki", sec.get("min_points", 5))
    sec["trend_epsilon"] = ask_float("Predikcija vlage - osjetljivost trenda", sec.get("trend_epsilon", 0.2))
    cfg["predictive_humidity"] = sec


def edit_status(cfg: dict):
    sec = dict(cfg.get("ai_kuca_status", {}) or {})
    sec["check_delay_sec"] = ask_int("Status checker - odgoda provjere (sek)", sec.get("check_delay_sec", 8))
    sec["app_names"] = ask_list("Status checker - popis appova", sec.get("app_names", []))
    cfg["ai_kuca_status"] = sec


def main():
    cfg = load_yaml(SYSTEM_YAML)
    changed = False
    client = None

    load_env(ENV_FILE)
    ha_url = os.getenv("HA_URL")
    ha_key = os.getenv("HA_KEY")
    if ha_url and ha_key:
        use_ha = input("Ucitati HA entitete za odabir iz liste? [Y/n]: ").strip().lower()
        if use_ha in ("", "y", "yes", "d", "da"):
            try:
                client = HAClient(ha_url, ha_key)
                client.load_entities()
                print(f"HA povezan. Ucitano entiteta: {len(client.entity_ids)}")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as ex:
                print(f"Upozorenje: HA lista entiteta nije dostupna ({ex}). Nastavljam rucno.")

    while True:
        print("\n=== SYSTEM EDITOR (MODULI) ===")
        print("1) Pregled system_configs.yaml")
        print("2) Logiranje")
        print("3) Log senzori (ai_kuca_log_sensors)")
        print("4) Grijanje")
        print("5) Overheat")
        print("6) Pumpa")
        print("7) Ventil")
        print("8) Boost")
        print("9) Ventilacija")
        print("10) Predikcija temperature")
        print("11) Predikcija vlage")
        print("12) Status checker")
        print("13) Spremi i izadi")
        print("0) Izadi bez spremanja")

        choice = input("Odabir: ").strip()

        if choice == "1":
            preview_system(cfg)
        elif choice == "2":
            edit_logging(cfg, client=client); changed = True
        elif choice == "3":
            edit_log_sensors(cfg); changed = True
        elif choice == "4":
            edit_heating(cfg, client=client); changed = True
        elif choice == "5":
            edit_overheat(cfg, client=client); changed = True
        elif choice == "6":
            edit_pump(cfg, client=client); changed = True
        elif choice == "7":
            edit_valve(cfg, client=client); changed = True
        elif choice == "8":
            edit_boost(cfg, client=client); changed = True
        elif choice == "9":
            edit_ventilation(cfg, client=client); changed = True
        elif choice == "10":
            edit_predictive(cfg, client=client); changed = True
        elif choice == "11":
            edit_predictive_humidity(cfg); changed = True
        elif choice == "12":
            edit_status(cfg); changed = True
        elif choice == "13":
            save_system_yaml_with_comments(SYSTEM_YAML, cfg)
            print(f"Spremljeno: {SYSTEM_YAML}")
            break
        elif choice == "0":
            if changed:
                confirm = input("Imas nespremljene promjene. Svejedno izadi? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes", "d", "da"):
                    continue
            break
        else:
            print("Neispravan odabir.")


if __name__ == "__main__":
    main()
    post_setup_menu()
