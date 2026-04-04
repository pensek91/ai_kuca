# AI_KUCA Documentation (EN)

This document explains the full `appdaemon` project and each active script, so a new person can quickly understand architecture, dependencies, and usage.

## 1) Project structure

- `appdaemon/.env`  
  Runtime environment variables (`HA_URL`, `HA_KEY`, `LOG_LEVEL`).
- `appdaemon/appdaemon.yaml`  
  Main AppDaemon config, reading env vars from `.env`.
- `appdaemon/docker-compose.yaml`  
  Container setup and `./apps` mount to `/conf/apps`.
- `appdaemon/apps/apps.yaml`  
  AppDaemon application list (module/class mapping).
- `appdaemon/apps/ai_kuca/config/system_configs.yaml`  
  System-level module settings (heating, pump, ventilation, logs, status...).
- `appdaemon/apps/ai_kuca/config/room_configs.yaml`  
  Room-level settings (climate/temp/humidity/fan/window/target).

## 2) Active AppDaemon apps

Apps are started only from `apps/apps.yaml`.

### 2.1 Config

- `ai_kuca.modules.config.validator.AIConfigValidator`  
  File: `apps/ai_kuca/modules/config/validator.py`

Responsibilities:
- Validates `system_configs.yaml` and `room_configs.yaml`.
- Manages HA helpers (input_text/input_select/input_number/input_boolean) for config UI.
- Saves UI config back to YAML.
- Triggers `appdaemon/reload` after config changes.

Additional helper scripts (not AppDaemon apps):
- `apps/ai_kuca/modules/config/ui.py`
- `apps/ai_kuca/modules/config/writer.py`

### 2.2 Heating

- `ai_kuca.modules.heating.main.AIHeatingMain` (`modules/heating/main.py`)  
  Main heating loop, ECO offset behavior, initial room target setup.

- `ai_kuca.modules.heating.overheat.AIOverheat` (`modules/heating/overheat.py`)  
  Overheat phase logic, target snapshot/restore, safety priority.

- `ai_kuca.modules.heating.valve.ValveControl` (`modules/heating/valve.py`)  
  Mixing valve pulse control (`open/close`) with interlock protection.

- `ai_kuca.modules.heating.pump.AIPump` (`modules/heating/pump.py`)  
  Autonomous heating pump control with min ON/OFF timing.

- `ai_kuca.modules.heating.boost.AIBoost` (`modules/heating/boost.py`)  
  Temporary room boost mode.

### 2.3 Predictive

- `ai_kuca.modules.predictive.temperature.PredictiveSensors` (`modules/predictive/temperature.py`)  
  Temperature predictions (15m/30m/1h), trends, predictive sensors.

- `ai_kuca.modules.predictive.humidity.PredictiveHumidity` (`modules/predictive/humidity.py`)  
  Humidity predictions per room (15m/30m/1h).

### 2.4 Ventilation

- `ai_kuca.modules.ventilation.main.AIVentilacijaMain` (`modules/ventilation/main.py`)  
  Room fan control based on humidity baseline, windows, and outdoor humidity.

### 2.5 System

- `ai_kuca.modules.system.status.AIKucaStatus` (`modules/system/status.py`)  
  One-time startup check for apps listed in `ai_kuca_status.app_names`.

## 3) Core scripts (`apps/ai_kuca/core`)

These are NOT standalone AppDaemon apps. They are shared libraries.

- `core/logger.py` – centralized HA log push + history.
- `core/utils.py` – utility helpers (`as_float`, `is_truthy_state`).
- `core/config_loader.py` – YAML load/save and env helper.
- `core/base_app.py` – optional base class for shared methods.

## 4) Modular independence

The project is modular and can be used partially.

### 4.1 Minimal profile: heating only

Keep in `apps/apps.yaml`:
- `ai_heating_main`
- `ai_overheat`
- `valve_control`
- `ai_pump`
- optional: `ai_boost`
- optional: `ai_config_validator`
- optional: `ai_kuca_status`

Disable:
- `predictive_sensors`
- `predictive_humidity`
- `ai_ventilation_main`

### 4.2 Profile: heating + ventilation (no predictive)

Enable:
- all heating apps
- `ai_ventilation_main`

Disable:
- `predictive_sensors`
- `predictive_humidity`

### 4.3 Profile: ventilation only

Enable:
- `ai_ventilation_main`
- optional: `ai_config_validator`
- optional: `ai_kuca_status`

Disable:
- heating apps
- predictive apps

Note:
- If you use `ai_kuca_status`, keep `ai_kuca_status.app_names` aligned with enabled apps.

## 5) Config dependencies by domain

- Heating apps use: `heating_main`, `overheat`, `pump`, `valve_control`, `boost`.
- Predictive uses: `predictive`, `predictive_humidity`, plus `room_configs.yaml`.
- Ventilation uses: `ventilation`, plus `room_configs.yaml`.
- Validator checks all sections.

## 6) Operational recommendations

Before major deploys:
1. Verify `apps/apps.yaml` contains only desired modules.
2. Verify `ai_kuca_status.app_names` matches enabled apps.
3. Backup `system_configs.yaml` and `room_configs.yaml`.

Reload after changes:
- Use `appdaemon/reload` (HA service) or restart container.

## 7) Quick FAQ

- "Will `core/` scripts run by themselves?"  
  No. They are helper libraries used by modules.

- "Can I disable all predictive logic?"  
  Yes, remove predictive apps from `apps/apps.yaml`.

- "Can I use only part of the system?"  
  Yes. The design is modular; enable only what you need.

## 8) Changelog (2026-04-04)

This section summarizes the key technical changes made for stability hardening and AI-learning readiness.

### 8.1 Docker and deployment

- `docker-compose.yaml`:
1. image pinned to `acockburn/appdaemon:4.4.2` (instead of `latest`) for deterministic deploys.
2. explicit mounts added for `conf/ai_logs`, `conf/dashboards`, `conf/namespaces`.
3. reduced volume overlap risk and runtime ambiguity.

- `editors/fresh_install.py`:
1. bootstrap compose template aligned with pinned image + explicit mount strategy.

### 8.2 Security and .env

- `.env` hardening:
1. file permissions set to `600`.
2. `.env` removed from git index (`git rm --cached .env`) and no longer versioned.

### 8.3 Logger and AI dataset base

- `apps/ai_universal_logger_v4.py`:
1. safer bool parsing (`_coerce_bool`) for key feature toggles.
2. payload sanitization (`_sanitize_payload`) plus sensitive key redaction (`REDACT_KEYS`).
3. improved exception handling with explicit warning/debug logs (no silent failures).
4. AI metadata fields added:
  - `schema_version`
  - `event_id`
  - `session_id`
5. minimal per-event state `snapshot` added (configurable via app args).
6. delayed outcome logging added for state changes:
  - `type=outcome`, `event=state_outcome`
  - `parent_event_id`
  - `target_state`
  - `state_after_delay`
  - `delay_sec`
  - `matched_target`

### 8.4 Export pipeline (JSONL -> CSV)

- `conf/ai_logs/export_ai_dataset.py`:
1. normalization extended to carry new AI metadata and outcome fields.
2. `ai_events.csv` and `trainer_ready.csv` schemas extended with:
  - `schema_version`, `event_id`, `session_id`
  - `parent_event_id`
  - `snapshot`
  - `target_state`, `state_after_delay`, `delay_sec`, `matched_target`
3. dedup logic improved: when `event_id` exists, it is used as primary dedup key.

### 8.5 Validator and UI stability

- `apps/ai_kuca/modules/config/validator.py`:
1. `validator_dry_run` now uses robust bool coercion.
2. `validator_ui_refresh_sec` introduced (default 15s, minimum 10s) instead of fixed 5s polling.
3. improved logging for debounce cancel and dropdown update failures.

### 8.6 Operational note

- `conf/ai_logs` is the runtime event base for future AI training.
- daily/weekly CSV export is active and confirmed in `conf/ai_logs/ai_trainer/export_cron.log`.
- outcome records appear after logger deployment and configured delay intervals elapse.
