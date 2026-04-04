import appdaemon.plugins.hass.hassapi as hass
import json
import os
import time
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

try:
    from ai_kuca.core.logger import push_log_to_ha
except Exception as ex:
    push_log_to_ha = None
    PUSH_LOG_IMPORT_ERROR = str(ex)
else:
    PUSH_LOG_IMPORT_ERROR = None


class AIUniversalLoggerV4(hass.Hass):

    SCHEMA_VERSION = 1

    REDACT_KEYS = {
        "token",
        "authorization",
        "password",
        "passwd",
        "secret",
        "api_key",
        "access_token",
        "refresh_token",
        "ha_key",
    }

    def initialize(self):
        self.version = "V4." + datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d%m%Y%H%M")
        self.log("AI Universal Logger V4 started")
        self.log(f"AI universal logger {self.version} pokrenut", level="INFO")
        args = getattr(self, "args", {}) or {}
        self.log_sensor_entity = str(args.get("ha_log_sensor_entity", "sensor.ai_kuca_log"))
        self.log_history_seconds = int(args.get("ha_log_history_seconds", 120))
        self.log_max_items = int(args.get("ha_log_max_items", 50))
        self._push_ha_startup(f"AI universal logger {self.version} pokrenut")
        self.timezone_name = str(args.get("timezone", "Europe/Zagreb"))
        try:
            self.timezone = ZoneInfo(self.timezone_name)
        except Exception as ex:
            self.timezone = ZoneInfo("UTC")
            self.log(f"AI Universal Logger: invalid timezone '{self.timezone_name}', fallback UTC ({ex})", level="WARNING")

        if PUSH_LOG_IMPORT_ERROR:
            self.log(
                f"AI Universal Logger: optional push_log_to_ha import failed ({PUSH_LOG_IMPORT_ERROR})",
                level="WARNING",
            )

        self.base_path = "/conf/ai_logs"
        os.makedirs(self.base_path, exist_ok=True)
        self.meta_logs_path = os.path.join(self.base_path, "meta_logs")
        self.user_actions_path = os.path.join(self.base_path, "user_actions")
        os.makedirs(self.meta_logs_path, exist_ok=True)
        os.makedirs(self.user_actions_path, exist_ok=True)
        self.daily_rotation = self._coerce_bool(args.get("daily_rotation", True), default=True)
        self.retention_days = int(args.get("retention_days", 60))
        self._cleanup_old_logs()
        self._write_log("logger_meta.log", {"time": self._now_str(), "type": "meta", "event": "logger_started"})
        self.session_window_sec = float(args.get("session_window_sec", 900.0))
        self._user_sessions = {}
        self.snapshot_enabled = self._coerce_bool(args.get("snapshot_enabled", True), default=True)
        self.outcome_enabled = self._coerce_bool(args.get("outcome_enabled", True), default=True)
        raw_delays = args.get("outcome_delays_sec", [300])
        if isinstance(raw_delays, (int, float, str)):
            raw_delays = [raw_delays]
        self.outcome_delays_sec = []
        for val in raw_delays or []:
            try:
                sec = int(float(val))
            except Exception:
                continue
            if sec > 0:
                self.outcome_delays_sec.append(sec)
        if not self.outcome_delays_sec:
            self.outcome_delays_sec = [300]
        self.snapshot_entities = list(
            args.get(
                "snapshot_entities",
                [
                    "sensor.temperatura_vani",
                    "sensor.cm_pelet_set_boiler_temperature",
                    "switch.pumpa_grijanja",
                    "input_boolean.overheat_active",
                    "input_boolean.ai_heating_eco",
                ],
            )
            or []
        )

        # Log only user-originated actions by default.
        # In Home Assistant, user_id is most reliably present on state_changed.new_state.context.
        self.log_state_changes = self._coerce_bool(args.get("log_state_changes", True), default=True)
        self.allowed_user_event_types = set(args.get("allowed_user_event_types", ["call_service", "state_changed"]))
        if self.log_state_changes:
            self.allowed_user_event_types.add("state_changed")

        self.ignored_state_domains = set(
            args.get(
                "ignored_state_domains",
                [
                    "sensor",
                    "binary_sensor",
                    "sun",
                    "weather",
                    "zone",
                    "device_tracker",
                    "input_select",
                    "input_text",
                    "input_number",
                    "input_datetime",
                ],
            )
        )
        self.allowed_action_domains = set(
            args.get(
                "allowed_action_domains",
                [
                    "light",
                    "switch",
                    "climate",
                    "fan",
                    "cover",
                    "scene",
                    "script",
                    "lock",
                    "media_player",
                    "vacuum",
                    "input_boolean",
                ],
            )
        )
        self.ignored_entity_prefixes = tuple(
            args.get(
                "ignored_entity_prefixes",
                [
                    "input_select.ai_kuca_",
                    "input_text.ai_kuca_",
                    "input_number.ai_kuca_",
                ],
            )
        )
        self.state_log_min_interval_sec = float(args.get("state_log_min_interval_sec", 10.0))
        self._last_state_log_ts = {}
        self.debug_missing_user_id = self._coerce_bool(args.get("debug_missing_user_id", True), default=True)
        self._missing_user_id_logs = 0
        self._missing_user_id_logs_max = int(args.get("debug_missing_user_id_max", 5))
        # When true, keep only direct user actions and drop chained actions
        # that usually come from HA automations/scripts (parent context present).
        self.direct_user_only = self._coerce_bool(args.get("direct_user_only", True), default=True)
        self.allowed_user_ids = {
            str(uid).strip() for uid in (args.get("allowed_user_ids", []) or []) if str(uid).strip()
        }
        self.blocked_user_ids = {
            str(uid).strip() for uid in (args.get("blocked_user_ids", []) or []) if str(uid).strip()
        }
        raw_user_labels = args.get("user_labels", {}) or {}
        self.user_labels = {str(k).strip(): str(v).strip() for k, v in raw_user_labels.items()}
        if not self.user_labels:
            # Default mapping for this installation; can still be overridden via args.user_labels.
            self.user_labels = {
                "50f9cf453a8f4a8184f85283aed1a9c9": "Vedran",
                "d877355c3f564309a5aa0b5f1b5abd54": "Renata",
                "c27daf5f220048dca13087884d5ec536": "HTC - Mob",
                "f4e0c7de1ea44897acc6ab1999986961": "AppDaemon - Skripta",
                "76d72028765543c59a34fbe820e7bbba": "Samsung",
                "beb8b5bd80fa48188089fbb034230aef": "Dashboard + Alexa",
            }

        # Subscribe to all events; filter strictly in callback to avoid missing user actions
        # on setups where service event name can vary.
        self.listen_event(self.log_event)

    def _push_ha_startup(self, message, level="INFO"):
        if not push_log_to_ha:
            return
        try:
            push_log_to_ha(
                app=self,
                message=message,
                level=level,
                sensor_entity=self.log_sensor_entity,
                history_seconds=self.log_history_seconds,
                max_items=self.log_max_items,
            )
        except Exception as ex:
            self.log(f"AI Universal Logger: HA startup push failed ({ex})", level="WARNING")
            return

    def _coerce_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "y", "on"):
                return True
            if text in ("0", "false", "no", "n", "off", ""):
                return False
        return default

    def _sanitize_payload(self, value, depth=0):
        if depth > 4:
            return "[max_depth]"

        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                key = str(k)
                if key.strip().lower() in self.REDACT_KEYS:
                    out[key] = "***REDACTED***"
                else:
                    out[key] = self._sanitize_payload(v, depth + 1)
            return out

        if isinstance(value, list):
            if len(value) > 40:
                trimmed = value[:40]
                return [self._sanitize_payload(v, depth + 1) for v in trimmed] + [f"...+{len(value) - 40} items"]
            return [self._sanitize_payload(v, depth + 1) for v in value]

        if isinstance(value, str):
            if len(value) > 512:
                return value[:512] + "...<truncated>"
            return value

        return value

    def _extract_user_id(self, payload, kwargs):
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        service_data = payload.get("service_data") if isinstance(payload.get("service_data"), dict) else {}
        service_context = service_data.get("context") if isinstance(service_data.get("context"), dict) else {}
        kw_context = kwargs.get("context") if isinstance(kwargs.get("context"), dict) else {}
        new_state = payload.get("new_state") if isinstance(payload.get("new_state"), dict) else {}
        old_state = payload.get("old_state") if isinstance(payload.get("old_state"), dict) else {}
        new_ctx = new_state.get("context") if isinstance(new_state.get("context"), dict) else {}
        old_ctx = old_state.get("context") if isinstance(old_state.get("context"), dict) else {}

        user_id = (
            new_ctx.get("user_id")
            or old_ctx.get("user_id")
            or context.get("user_id")
            or service_context.get("user_id")
            or payload.get("user_id")
            or service_data.get("user_id")
            or kw_context.get("user_id")
        )

        context_id = (
            new_ctx.get("id")
            or old_ctx.get("id")
            or context.get("id")
            or service_context.get("id")
            or kw_context.get("id")
        )
        parent_context_id = (
            new_ctx.get("parent_id")
            or old_ctx.get("parent_id")
            or context.get("parent_id")
            or service_context.get("parent_id")
            or kw_context.get("parent_id")
        )
        return user_id, context_id, parent_context_id

    def _write_log(self, filename, data):
        try:
            filepath = self._resolve_filepath(filename)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            self.log(f"ERROR writing log ({filename}): {e}", level="WARNING")

    def _get_session_id(self, user_id, now_ts):
        session = self._user_sessions.get(user_id)
        if session and (now_ts - session.get("last_ts", 0.0)) <= self.session_window_sec:
            session["last_ts"] = now_ts
            self._user_sessions[user_id] = session
            return session.get("id")

        sid = str(uuid4())
        self._user_sessions[user_id] = {"id": sid, "last_ts": now_ts}
        return sid

    def _build_snapshot(self):
        if not self.snapshot_enabled:
            return None

        snapshot = {}
        for entity_id in self.snapshot_entities:
            try:
                snapshot[entity_id] = self.get_state(entity_id)
            except Exception:
                snapshot[entity_id] = None
        return snapshot

    def _schedule_outcome_logs(self, *, event_id, session_id, user_id, user_name, source, context_id, parent_context_id, entity_id, target_state):
        if not self.outcome_enabled:
            return
        if not entity_id:
            return

        for delay_sec in self.outcome_delays_sec:
            try:
                self.run_in(
                    self._log_outcome,
                    delay_sec,
                    event_id=event_id,
                    session_id=session_id,
                    user_id=user_id,
                    user_name=user_name,
                    source=source,
                    context_id=context_id,
                    parent_context_id=parent_context_id,
                    entity_id=entity_id,
                    target_state=target_state,
                    delay_sec=delay_sec,
                )
            except Exception as ex:
                self.log(f"AI Universal Logger: failed to schedule outcome ({entity_id}, {delay_sec}s): {ex}", level="DEBUG")

    def _log_outcome(self, kwargs):
        entity_id = kwargs.get("entity_id")
        if not entity_id:
            return

        target_state = kwargs.get("target_state")
        observed_state = None
        try:
            observed_state = self.get_state(entity_id)
        except Exception:
            observed_state = None

        if target_state in (None, "", "unknown", "unavailable"):
            matched_target = None
        else:
            matched_target = str(observed_state) == str(target_state)

        outcome_entry = {
            "time": self._now_str(),
            "schema_version": self.SCHEMA_VERSION,
            "event_id": str(uuid4()),
            "parent_event_id": kwargs.get("event_id"),
            "session_id": kwargs.get("session_id"),
            "type": "outcome",
            "event": "state_outcome",
            "user_id": kwargs.get("user_id"),
            "user_name": kwargs.get("user_name"),
            "source": "system_outcome",
            "automation_guess": False,
            "context_id": kwargs.get("context_id"),
            "parent_context_id": kwargs.get("parent_context_id"),
            "entity_id": entity_id,
            "domain": (entity_id.split(".", 1)[0] if "." in entity_id else ""),
            "target_state": target_state,
            "state_after_delay": observed_state,
            "delay_sec": kwargs.get("delay_sec"),
            "matched_target": matched_target,
            "snapshot": self._build_snapshot(),
        }
        self._write_log("user_actions.log", outcome_entry)

    def _resolve_filepath(self, filename):
        base_dir = self.base_path
        if filename.startswith("logger_meta"):
            base_dir = self.meta_logs_path
        elif filename.startswith("user_actions"):
            base_dir = self.user_actions_path

        if not self.daily_rotation or not filename.endswith(".log"):
            return os.path.join(base_dir, filename)

        base = filename[:-4]
        day = self._now().strftime("%Y-%m-%d")
        return os.path.join(base_dir, f"{base}_{day}.log")

    def _cleanup_old_logs(self):
        if self.retention_days <= 0:
            return
        cutoff_ts = self._now().timestamp() - (self.retention_days * 86400)
        for directory in (self.user_actions_path, self.meta_logs_path):
            try:
                for name in os.listdir(directory):
                    if not name.endswith(".log"):
                        continue
                    path = os.path.join(directory, name)
                    try:
                        if os.path.getmtime(path) < cutoff_ts:
                            os.remove(path)
                    except Exception as ex:
                        self.log(f"AI Universal Logger: cleanup skip for {path} ({ex})", level="DEBUG")
                        continue
            except Exception as ex:
                self.log(f"AI Universal Logger: cleanup directory failed ({directory}) ({ex})", level="WARNING")
                continue

    def _now(self):
        return datetime.now(self.timezone)

    def _now_str(self):
        return self._now().strftime("%Y-%m-%d %H:%M:%S.%f%z")

    def log_event(self, event_name, data, kwargs):
        payload = data if isinstance(data, dict) else {}
        is_service_like = isinstance(payload, dict) and ("domain" in payload and "service" in payload)
        if (event_name not in self.allowed_user_event_types) and not is_service_like:
            return

        if event_name == "state_changed" and not self.log_state_changes:
            return

        user_id, context_id, parent_context_id = self._extract_user_id(payload, kwargs)
        if not user_id:
            if self.debug_missing_user_id and self._missing_user_id_logs < self._missing_user_id_logs_max:
                self._missing_user_id_logs += 1
                keys = sorted(payload.keys()) if isinstance(payload, dict) else []
                self.log(
                    f"AI Universal Logger: event bez user_id | event={event_name} | kljucevi={keys} | domain={payload.get('domain')} | service={payload.get('service')}",
                    level="DEBUG",
                )
            return

        source = "human"
        automation_guess = False
        if parent_context_id:
            source = "automation_guess"
            automation_guess = True

        if self.direct_user_only and parent_context_id:
            return

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            return

        if user_id in self.blocked_user_ids:
            return

        if event_name == "state_changed":
            entity_id = payload.get("entity_id", "")
            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            if domain in self.ignored_state_domains:
                return
            if self.allowed_action_domains and domain not in self.allowed_action_domains:
                return
            if entity_id.startswith(self.ignored_entity_prefixes):
                return

            now_ts = datetime.now().timestamp()
            last_ts = self._last_state_log_ts.get(entity_id, 0.0)
            if (now_ts - last_ts) < self.state_log_min_interval_sec:
                return
            self._last_state_log_ts[entity_id] = now_ts

        now_ts = time.time()
        event_id = str(uuid4())
        session_id = self._get_session_id(user_id, now_ts)
        snapshot = self._build_snapshot()

        log_entry = {
            "time": self._now_str(),
            "schema_version": self.SCHEMA_VERSION,
            "event_id": event_id,
            "session_id": session_id,
            "type": "event",
            "event": event_name,
            "user_id": user_id,
            "user_name": self.user_labels.get(user_id),
            "source": source,
            "automation_guess": automation_guess,
            "context_id": context_id,
            "parent_context_id": parent_context_id,
            "snapshot": snapshot,
            "data": self._sanitize_payload(payload),
        }

        if event_name == "state_changed":
            new_state = payload.get("new_state") if isinstance(payload.get("new_state"), dict) else {}
            old_state = payload.get("old_state") if isinstance(payload.get("old_state"), dict) else {}
            log_entry = {
                "time": self._now_str(),
                "schema_version": self.SCHEMA_VERSION,
                "event_id": event_id,
                "session_id": session_id,
                "type": "state",
                "event": event_name,
                "user_id": user_id,
                "user_name": self.user_labels.get(user_id),
                "source": source,
                "automation_guess": automation_guess,
                "context_id": context_id,
                "parent_context_id": parent_context_id,
                "snapshot": snapshot,
                "entity_id": payload.get("entity_id"),
                "old_state": old_state.get("state"),
                "new_state": new_state.get("state"),
                "domain": (payload.get("entity_id", "").split(".", 1)[0] if "." in payload.get("entity_id", "") else ""),
            }
            self._schedule_outcome_logs(
                event_id=event_id,
                session_id=session_id,
                user_id=user_id,
                user_name=self.user_labels.get(user_id),
                source=source,
                context_id=context_id,
                parent_context_id=parent_context_id,
                entity_id=payload.get("entity_id"),
                target_state=new_state.get("state"),
            )
        self._write_log("user_actions.log", log_entry)
