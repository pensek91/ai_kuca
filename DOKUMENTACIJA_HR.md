# AI_KUCA Dokumentacija (HR)

Ova dokumentacija opisuje cijeli projekt `appdaemon` i svaku aktivnu skriptu tako da i osoba koja prvi put vidi projekt može brzo razumjeti arhitekturu, ovisnosti i način korištenja.

## 1) Struktura projekta

- `appdaemon/.env`  
  Runtime varijable okoline (`HA_URL`, `HA_KEY`, `LOG_LEVEL`).
- `appdaemon/appdaemon.yaml`  
  Glavna AppDaemon konfiguracija, koristi env varijable iz `.env`.
- `appdaemon/docker-compose.yaml`  
  Pokretanje AppDaemon kontejnera i mount `./apps` u `/conf/apps`.
- `appdaemon/apps/apps.yaml`  
  Lista AppDaemon aplikacija (module/class mapiranje).
- `appdaemon/apps/ai_kuca/config/system_configs.yaml`  
  Sustavske postavke modula (grijanje, pumpa, ventilacija, log, status...).
- `appdaemon/apps/ai_kuca/config/room_configs.yaml`  
  Konfiguracija soba (climate/temp/humidity/fan/window/target).

## 2) Aktivne AppDaemon aplikacije

Aplikacije se pokreću isključivo iz `apps/apps.yaml`.

### 2.1 Config

- `ai_kuca.modules.config.validator.AIConfigValidator`  
  Datoteka: `apps/ai_kuca/modules/config/validator.py`

Što radi:
- Validira `system_configs.yaml` i `room_configs.yaml`.
- Upravlja HA helperima (input_text/input_select/input_number/input_boolean) za UI konfiguraciju.
- Omogućava spremanje konfiguracije iz UI-a natrag u YAML.
- Triggera `appdaemon/reload` nakon izmjena.

Napomena:
- Ovo je “administrativni” modul. Ostali moduli mogu raditi bez njega ako su YAML datoteke ispravno popunjene ručno.

Dodatne helper skripte (ne AppDaemon app):
- `apps/ai_kuca/modules/config/ui.py` – helper za formatiranje summary teksta.
- `apps/ai_kuca/modules/config/writer.py` – helper za validaciju/pisanje YAML-a.

### 2.2 Heating

- `ai_kuca.modules.heating.main.AIHeatingMain` (`modules/heating/main.py`)  
  Glavni ciklus grijanja, ECO offset, inicijalno postavljanje targeta po sobama.

- `ai_kuca.modules.heating.overheat.AIOverheat` (`modules/heating/overheat.py`)  
  Overheat logika (faze, snapshot/restore targeta, prioritet sigurnosti).

- `ai_kuca.modules.heating.valve.ValveControl` (`modules/heating/valve.py`)  
  Impulsna regulacija miješajućeg ventila (`open/close`) uz interlock zaštitu.

- `ai_kuca.modules.heating.pump.AIPump` (`modules/heating/pump.py`)  
  Autonomna kontrola pumpe grijanja s minimalnim ON/OFF vremenima.

- `ai_kuca.modules.heating.boost.AIBoost` (`modules/heating/boost.py`)  
  Privremeni “boost” režim za odabrane sobe.

### 2.3 Predictive

- `ai_kuca.modules.predictive.temperature.PredictiveSensors` (`modules/predictive/temperature.py`)  
  Predikcija temperature (15m/30m/1h), trendovi i senzori predikcije.

- `ai_kuca.modules.predictive.humidity.PredictiveHumidity` (`modules/predictive/humidity.py`)  
  Predikcija vlage po sobama (15m/30m/1h).

### 2.4 Ventilation

- `ai_kuca.modules.ventilation.main.AIVentilacijaMain` (`modules/ventilation/main.py`)  
  Kontrola ventilatora po sobama na temelju vlage, baseline-a, prozora i vanjske vlage.

### 2.5 System

- `ai_kuca.modules.system.status.AIKucaStatus` (`modules/system/status.py`)  
  Jednokratna provjera dostupnosti appova navedenih u `ai_kuca_status.app_names`.

## 3) Core skripte (`apps/ai_kuca/core`)

Ove skripte se NE pokreću kao samostalni AppDaemon appovi. Koriste se kao zajedničke biblioteke.

- `core/logger.py`  
  Funkcija `push_log_to_ha(...)` za centralizirani HA log senzor + history.

- `core/utils.py`  
  Pomoćne funkcije (`as_float`, `is_truthy_state`).

- `core/config_loader.py`  
  Učitavanje/spremanje YAML configa i env helper.

- `core/base_app.py`  
  Bazna klasa s helper metodama (trenutno nije obavezna u svim modulima, ali služi kao baza za daljnju standardizaciju).

## 4) Modulna neovisnost (ključni dio)

Projekt je organiziran modularno i može se koristiti parcijalno.

### 4.1 Minimalni profil: samo grijanje

U `apps/apps.yaml` ostavi:
- `ai_heating_main`
- `ai_overheat`
- `valve_control`
- `ai_pump`
- (opcionalno) `ai_boost`
- (opcionalno) `ai_config_validator`
- (opcionalno) `ai_kuca_status`

Isključi:
- `predictive_sensors`
- `predictive_humidity`
- `ai_ventilation_main`

### 4.2 Profil: grijanje + ventilacija (bez predikcije)

Uključi:
- sve iz grijanja
- `ai_ventilation_main`

Isključi:
- `predictive_sensors`
- `predictive_humidity`

### 4.3 Profil: samo ventilacija

Uključi:
- `ai_ventilation_main`
- (opcionalno) `ai_config_validator`
- (opcionalno) `ai_kuca_status`

Isključi:
- heating moduli
- predictive moduli

Napomena:
- Ako koristiš `ai_kuca_status`, uskladi `ai_kuca_status.app_names` sa stvarno aktivnim appovima.

## 5) Ovisnosti po konfiguraciji

- Grijanje moduli primarno koriste sekcije: `heating_main`, `overheat`, `pump`, `valve_control`, `boost`.
- Predikcija koristi: `predictive`, `predictive_humidity` + `room_configs.yaml`.
- Ventilacija koristi: `ventilation` + `room_configs.yaml`.
- Validator koristi sve sekcije jer validira cijeli sustav.

## 6) Operativne preporuke

- Prije svakog većeg deploya:
1. Provjeri `apps/apps.yaml` (samo željeni moduli).
2. Provjeri `ai_kuca_status.app_names` (da ne prijavljuje lažne greške).
3. Napravi backup `system_configs.yaml` i `room_configs.yaml`.

- Za reload nakon izmjena:
- `appdaemon/reload` (kroz HA service ili restart kontejnera).

## 7) Brzi FAQ

- "Hoće li `core/` skripte raditi same?"  
  Ne. To su helper biblioteke; koriste ih moduli.

- "Mogu li isključiti cijeli predikcijski dio?"  
  Da, samo ukloni predictive appove iz `apps/apps.yaml`.

- "Mogu li koristiti samo dio sustava?"  
  Da, dizajn je modularan; aktiviraš samo module koje želiš.
