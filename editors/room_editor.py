import yaml
import subprocess
import sys
import os
import json
import urllib.error
import urllib.request
from pathlib import Path
import re

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
ROOMS_YAML = ROOT / "apps" / "ai_kuca" / "config" / "room_configs.yaml"
HA_HELPERS_YAML = ROOT / "HA_datoteke" / "ha_helpers.yaml"
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


def ask_entity(label: str, domain: str, current: str = "", client: HAClient | None = None) -> str:
    options = _domain_entities(client, domain)
    if options:
        picked = _select_from_list(f"{label} ({domain}.*)", options, current_value=current)
        if picked is not None:
            return picked

    suffix = f" [{current}]" if current else ""
    raw = input(f"{label}{suffix} (Enter=zadrzi, -=obrisi): ").strip()
    if not raw:
        return current
    if raw == "-":
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


def ask_yes_no(question: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{question} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes", "d", "da"):
            return True
        if raw in ("n", "no", "ne"):
            return False
        print("Neispravan unos. Upiši y ili n.")


def ask_target_step(current):
    cur = current if current not in (None, "", 0) else 0.5
    while True:
        raw = input(f"Korak target temperature (0.5 ili 1.0) [{cur}]: ").strip()
        if not raw:
            value = float(cur)
        else:
            try:
                value = float(raw)
            except ValueError:
                print("Neispravan broj.")
                continue
        if value in (0.5, 1.0):
            return value
        print("Dozvoljeno je samo 0.5 ili 1.0")


def ask_entity_list(label: str, domain: str, current_list, client: HAClient | None = None):
    current_list = current_list or []
    current = ", ".join(current_list)
    options = _domain_entities(client, domain)
    if options:
        print(f"\n{label} ({domain}.*)")
        print("Unesi vise entiteta odvojeno zarezom.")
        print("Primjer: binary_sensor.prozor_1, binary_sensor.vrata_2")
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


def normalize_room_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def room_target_helper_entity(room_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]", "", normalize_room_name(room_name)) or "room"
    return f"input_number.ai_kuca_target_{slug}"


def room_target_helper_key(room_name: str) -> str:
    return room_target_helper_entity(room_name).split(".", 1)[1]


def room_target_helper_name(room_name: str) -> str:
    pretty = normalize_room_name(room_name).replace("_", " ").title()
    return f"AI Kuca Target {pretty}"


def sync_room_target_helpers_yaml(rooms: dict):
    if not HA_HELPERS_YAML.exists():
        return

    data = load_yaml(HA_HELPERS_YAML)
    input_numbers = data.get("input_number") if isinstance(data.get("input_number"), dict) else {}

    managed_keys = {k for k in input_numbers.keys() if str(k).startswith("ai_kuca_target_")}
    wanted_keys = set()

    for room_name, room_cfg in (rooms or {}).items():
        key = room_target_helper_key(room_name)
        wanted_keys.add(key)
        existing = input_numbers.get(key, {}) if isinstance(input_numbers.get(key), dict) else {}
        helper_cfg = {
            "name": existing.get("name") or room_target_helper_name(room_name),
            "min": existing.get("min", 8),
            "max": existing.get("max", 35),
            "step": existing.get("step", 0.5),
            "unit_of_measurement": existing.get("unit_of_measurement", "°C"),
        }
        # Bez 'initial' da HA nakon restarta vrati zadnju poznatu vrijednost helpera.
        input_numbers[key] = helper_cfg

    for stale in sorted(managed_keys - wanted_keys):
        input_numbers.pop(stale, None)

    data["input_number"] = input_numbers
    save_yaml(HA_HELPERS_YAML, data)


def preview_rooms(rooms: dict):
    print("\n--- Pregled room_configs.yaml ---")
    if not rooms:
        print("Nema konfiguriranih soba.")
        return
    print(yaml.safe_dump(rooms, sort_keys=False, allow_unicode=True))


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


def edit_predictive_params(room: dict):
    pred = dict(room.get("predictive", {}) or {})
    print("\n--- Napredne prediktivne postavke za ovu sobu (Enter=zadrži, -=obrisi) ---")
    pred["smart_boost_enabled"] = ask_yes_no("Pametni boost omogućen?", pred.get("smart_boost_enabled", True))
    pred["smart_boost_delta"] = ask_float("Pametni boost: prag razlike (°C)", pred.get("smart_boost_delta", 2.0))
    pred["smart_boost_max"] = ask_float("Pametni boost: maksimalni target (°C)", pred.get("smart_boost_max", 25.0))
    pred["smart_boost_deadband"] = ask_float("Pametni boost: deadband (°C)", pred.get("smart_boost_deadband", 0.5))
    room["predictive"] = pred
    return room


def edit_room(room_name: str, room: dict, client: HAClient | None = None) -> dict:
    room = dict(room or {})
    print(f"\nUredivanje sobe: {room_name}")

    room["target_input"] = room_target_helper_entity(room_name)

    room["climate"] = ask_entity(
        "Klima/radijator entitet (opcionalno; za grijanje)",
        "climate",
        current=room.get("climate", ""),
        client=client,
    )

    room["target"] = ask_float("Ciljana temperatura sobe (opcionalno)", room.get("target", 21.0))
    room["target_step"] = ask_target_step(room.get("target_step", 0.5))

    room["temp_sensor"] = ask_entity(
        "Senzor temperature (opcionalno; za predikciju)",
        "sensor",
        current=room.get("temp_sensor", ""),
        client=client,
    )

    room["humidity_sensor"] = ask_entity(
        "Senzor vlage (opcionalno; za vlagu/ventilaciju)",
        "sensor",
        current=room.get("humidity_sensor", ""),
        client=client,
    )

    fan_val = ask_entity(
        "Ventilator (opcionalno)",
        "fan",
        current=room.get("fan", ""),
        client=client,
    )
    if fan_val:
        room["fan"] = fan_val
    else:
        room.pop("fan", None)

    room["window_sensors"] = ask_entity_list(
        "Senzori prozora/vrata (zarezom)",
        "binary_sensor",
        room.get("window_sensors", []),
        client=client,
    )

    if room.get("climate"):
        pred = dict(room.get("predictive", {}) or {})
        pred["auto_apply_targets"] = ask_yes_no(
            "Predikcija - dozvoli automatsko korigiranje targeta za ovu sobu?",
            bool(pred.get("auto_apply_targets", True)),
        )
        if ask_yes_no("Predikcija - uredi napredne limite za ovu sobu?", False):
            pred["deadband"] = ask_float(
                "Predikcija - deadband za ovu sobu (C)",
                pred.get("deadband", 0.2),
            )
            pred["max_step_per_cycle"] = ask_float(
                "Predikcija - max promjena po ciklusu za ovu sobu (C)",
                pred.get("max_step_per_cycle", 0.5),
            )
            pred["min_temp"] = ask_float(
                "Predikcija - minimalni target za ovu sobu (C)",
                pred.get("min_temp", 8.0),
            )
            pred["max_temp"] = ask_float(
                "Predikcija - maksimalni target za ovu sobu (C)",
                pred.get("max_temp", 35.0),
            )
        room["predictive"] = pred
    else:
        room.pop("predictive", None)

    if room.get("fan"):
        vent = dict(room.get("ventilation", {}) or {})
        edit_vent = input("Uredi ventilation parametre za ovu sobu? [y/N]: ").strip().lower()
        if edit_vent in ("y", "yes", "d", "da"):
            vent["delta_on"] = ask_float("Ventilacija - ukljuci na +delta vlage", vent.get("delta_on", 4.0))
            vent["delta_off"] = ask_float("Ventilacija - iskljuci na +delta vlage", vent.get("delta_off", 2.0))
            vent["abs_on"] = ask_float("Ventilacija - apsolutni prag ukljucenja (%)", vent.get("abs_on", 70.0))
            vent["abs_off"] = ask_float("Ventilacija - apsolutni prag iskljucenja (%)", vent.get("abs_off", 60.0))
            vent["min_on_sec"] = int(ask_float("Ventilacija - minimalno vrijeme rada (sek)", vent.get("min_on_sec", 300)))
            vent["min_off_sec"] = int(ask_float("Ventilacija - minimalna pauza (sek)", vent.get("min_off_sec", 180)))
            room["ventilation"] = vent
    else:
        room.pop("ventilation", None)

    # Nakon svih osnovnih polja, ponudi napredne prediktivne postavke
    if ask_yes_no("Uredi napredne prediktivne postavke za ovu sobu?", False):
        room = edit_predictive_params(room)
    return room


def main():
    rooms = load_yaml(ROOMS_YAML)
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
        print("\n=== ROOM EDITOR (SOBE) ===")
        print("1) Pregled room_configs.yaml")
        print("2) Prikazi sve sobe")
        print("3) Uredi postojecu sobu")
        print("4) Dodaj novu sobu")
        print("5) Obrisi sobu")
        print("6) Spremi i izadi")
        print("7) Izadi bez spremanja")

        choice = input("Odabir: ").strip()

        if choice == "1":
            preview_rooms(rooms)

        elif choice == "2":
            if not rooms:
                print("Nema soba.")
            else:
                for name in sorted(rooms):
                    print(f"- {name}")

        elif choice == "3":
            name = normalize_room_name(input("Naziv sobe za uredivanje: ").strip())
            if not name or name not in rooms:
                print("Soba ne postoji.")
                continue
            rooms[name] = edit_room(name, rooms.get(name, {}), client=client)
            changed = True

        elif choice == "4":
            name = normalize_room_name(input("Naziv nove sobe: ").strip())
            if not name:
                print("Naziv je obavezan.")
                continue
            if name in rooms:
                print("Soba vec postoji, otvaram uredivanje.")
            rooms[name] = edit_room(name, rooms.get(name, {}), client=client)
            changed = True

        elif choice == "5":
            name = normalize_room_name(input("Naziv sobe za brisanje: ").strip())
            if name in rooms:
                confirm = input(f"Potvrdi brisanje sobe '{name}'? [y/N]: ").strip().lower()
                if confirm in ("y", "yes", "d", "da"):
                    del rooms[name]
                    changed = True
                    print("Obrisano.")
            else:
                print("Soba ne postoji.")

        elif choice == "6":
            save_yaml(ROOMS_YAML, rooms)
            sync_room_target_helpers_yaml(rooms)
            print(f"Spremljeno: {ROOMS_YAML}")
            break

        elif choice == "7":
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
