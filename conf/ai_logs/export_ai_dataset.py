#!/usr/bin/env python3
"""Export AI-ready datasets and summaries from daily AppDaemon logs.

Input files expected in log dir (JSONL):
- user_actions_YYYY-MM-DD.log
- logger_meta_YYYY-MM-DD.log (optional)

Outputs (under output dir):
- ai_events.csv
- ai_events.parquet (optional, if pandas+pyarrow available and requested)
- daily_summary.csv
- weekly_summary.csv
- trainer_ready.csv (cumulative)
- trainer_ready.parquet (optional)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple


DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build AI-ready dataset + daily/weekly summaries from AppDaemon logs."
    )
    parser.add_argument(
        "--log-dir",
        default=".",
        help="Directory containing user_actions_*.log and logger_meta_*.log files.",
    )
    parser.add_argument(
        "--output-dir",
        default="./ai_trainer",
        help="Directory where exported files will be written.",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Lower bound date (YYYY-MM-DD), inclusive.",
    )
    parser.add_argument(
        "--to-date",
        default=None,
        help="Upper bound date (YYYY-MM-DD), inclusive.",
    )
    parser.add_argument(
        "--include-meta",
        action="store_true",
        help="Include logger_meta_*.log events in ai_events.csv/parquet.",
    )
    parser.add_argument(
        "--with-parquet",
        action="store_true",
        help="Also export ai_events.parquet (requires pandas + pyarrow).",
    )
    parser.add_argument(
        "--trainer-retention-days",
        type=int,
        default=365,
        help="How long to keep rows in cumulative trainer_ready dataset (default: 365).",
    )
    parser.add_argument(
        "--trainer-include-automation-guess",
        action="store_true",
        help="Include rows marked automation_guess in trainer_ready dataset.",
    )
    return parser.parse_args()


def parse_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def extract_date_from_name(path: str) -> Optional[dt.date]:
    m = DATE_RE.search(os.path.basename(path))
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def list_input_files(log_dir: str, include_meta: bool) -> List[str]:
    files = []
    files.extend(sorted(glob.glob(os.path.join(log_dir, "user_actions", "user_actions_*.log"))))
    files.extend(sorted(glob.glob(os.path.join(log_dir, "user_actions_*.log"))))
    if include_meta:
        files.extend(sorted(glob.glob(os.path.join(log_dir, "meta_logs", "logger_meta_*.log"))))
        files.extend(sorted(glob.glob(os.path.join(log_dir, "logger_meta_*.log"))))
    return files


def date_in_range(value: Optional[dt.date], start: Optional[dt.date], end: Optional[dt.date]) -> bool:
    if value is None:
        return True
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def safe_iso_week(d: dt.date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def parse_timestamp(ts: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[dt.date], Optional[str]]:
    if not ts:
        return None, None, None
    raw = str(ts).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = dt.datetime.strptime(raw, fmt)
            return parsed, parsed.date(), safe_iso_week(parsed.date())
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed, parsed.date(), safe_iso_week(parsed.date())
    except ValueError:
        pass
    return None, None, None


def infer_action(row: Dict[str, object]) -> str:
    event = str(row.get("event") or "")
    domain = str(row.get("domain") or "")
    old_state = str(row.get("old_state") or "")
    new_state = str(row.get("new_state") or "")

    if event == "state_changed":
        if old_state != new_state:
            if new_state == "on":
                return "turned_on"
            if new_state == "off":
                return "turned_off"
            return "state_changed"
        return "state_refreshed"

    if domain and event:
        return f"{domain}_{event}"
    return event or "unknown"


def infer_part_of_day(hour: Optional[int]) -> Optional[str]:
    if hour is None:
        return None
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def normalize_row(obj: Dict[str, object], file_date: Optional[dt.date]) -> Dict[str, object]:
    parsed_ts, event_date, week = parse_timestamp(obj.get("time"))
    if event_date is None:
        event_date = file_date
    if week is None and event_date is not None:
        week = safe_iso_week(event_date)

    row = {
        "time": obj.get("time"),
        "schema_version": obj.get("schema_version"),
        "event_id": obj.get("event_id"),
        "parent_event_id": obj.get("parent_event_id"),
        "session_id": obj.get("session_id"),
        "date": event_date.isoformat() if event_date else None,
        "week": week,
        "type": obj.get("type"),
        "event": obj.get("event"),
        "user_id": obj.get("user_id"),
        "user_name": obj.get("user_name"),
        "source": obj.get("source"),
        "automation_guess": bool(obj.get("automation_guess", False)),
        "entity_id": obj.get("entity_id"),
        "domain": obj.get("domain"),
        "old_state": obj.get("old_state"),
        "new_state": obj.get("new_state"),
        "target_state": obj.get("target_state"),
        "state_after_delay": obj.get("state_after_delay"),
        "delay_sec": obj.get("delay_sec"),
        "matched_target": obj.get("matched_target"),
        "context_id": obj.get("context_id"),
        "parent_context_id": obj.get("parent_context_id"),
        "snapshot": json.dumps(obj.get("snapshot"), ensure_ascii=True, sort_keys=True)
        if isinstance(obj.get("snapshot"), dict)
        else None,
    }
    row["action"] = infer_action(row)
    row["is_human"] = row.get("source") == "human"
    row["is_state_event"] = row.get("event") == "state_changed"
    if parsed_ts is not None:
        row["hour"] = parsed_ts.hour
        row["weekday"] = parsed_ts.strftime("%A")
    else:
        row["hour"] = None
        row["weekday"] = None
    row["is_weekend"] = row["weekday"] in ("Saturday", "Sunday")
    row["part_of_day"] = infer_part_of_day(row["hour"])
    return row


def read_rows(files: Iterable[str], start: Optional[dt.date], end: Optional[dt.date]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in files:
        file_date = extract_date_from_name(path)
        if not date_in_range(file_date, start, end):
            continue

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                row = normalize_row(obj, file_date)
                date_str = row.get("date")
                if date_str:
                    d = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
                    if not date_in_range(d, start, end):
                        continue
                rows.append(row)
    return rows


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_csv(path: str, rows: List[Dict[str, object]], headers: List[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in headers})


def build_daily_summary(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    counter = Counter()
    for r in rows:
        key = (
            r.get("date"),
            r.get("user_name") or r.get("user_id"),
            r.get("domain"),
            r.get("action"),
        )
        counter[key] += 1

    out = []
    for (date, user, domain, action), count in sorted(counter.items()):
        out.append(
            {
                "date": date,
                "user": user,
                "domain": domain,
                "action": action,
                "count": count,
            }
        )
    return out


def build_weekly_summary(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    counter = Counter()
    for r in rows:
        key = (
            r.get("week"),
            r.get("user_name") or r.get("user_id"),
            r.get("domain"),
            r.get("action"),
        )
        counter[key] += 1

    out = []
    for (week, user, domain, action), count in sorted(counter.items()):
        out.append(
            {
                "week": week,
                "user": user,
                "domain": domain,
                "action": action,
                "count": count,
            }
        )
    return out


def write_parquet(path: str, rows: List[Dict[str, object]]) -> None:
    try:
        import pandas as pd  # type: ignore
    except Exception as ex:
        raise RuntimeError("Parquet export requires pandas and pyarrow.") from ex

    df = pd.DataFrame(rows)
    try:
        df.to_parquet(path, index=False)
    except Exception as ex:
        raise RuntimeError("Failed to write parquet. Install pyarrow in environment.") from ex


def build_trainer_rows(rows: List[Dict[str, object]], include_automation_guess: bool) -> List[Dict[str, object]]:
    trainer_rows: List[Dict[str, object]] = []
    for r in rows:
        if not r.get("is_human"):
            continue
        if not include_automation_guess and bool(r.get("automation_guess", False)):
            continue

        trainer_rows.append(
            {
                "time": r.get("time"),
                "schema_version": r.get("schema_version"),
                "event_id": r.get("event_id"),
                "session_id": r.get("session_id"),
                "date": r.get("date"),
                "week": r.get("week"),
                "weekday": r.get("weekday"),
                "hour": r.get("hour"),
                "part_of_day": r.get("part_of_day"),
                "is_weekend": r.get("is_weekend"),
                "user_id": r.get("user_id"),
                "user_name": r.get("user_name"),
                "entity_id": r.get("entity_id"),
                "domain": r.get("domain"),
                "action": r.get("action"),
                "old_state": r.get("old_state"),
                "new_state": r.get("new_state"),
                "source": r.get("source"),
                "automation_guess": r.get("automation_guess"),
                "context_id": r.get("context_id"),
                "parent_context_id": r.get("parent_context_id"),
                "snapshot": r.get("snapshot"),
            }
        )
    return trainer_rows


def load_csv_rows(path: str) -> List[Dict[str, object]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, object]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(dict(row))
    return out


def row_key(row: Dict[str, object]) -> Tuple[str, str, str, str, str, str]:
    event_id = str(row.get("event_id") or "")
    if event_id:
        return (event_id, "", "", "", "", "")

    return (
        str(row.get("time") or ""),
        str(row.get("user_id") or ""),
        str(row.get("entity_id") or ""),
        str(row.get("action") or ""),
        str(row.get("context_id") or ""),
        str(row.get("new_state") or ""),
    )


def merge_dedup(existing: List[Dict[str, object]], new_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    seen = set()
    for row in existing + new_rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def prune_by_days(rows: List[Dict[str, object]], retention_days: int) -> List[Dict[str, object]]:
    if retention_days <= 0:
        return rows
    cutoff = dt.date.today() - dt.timedelta(days=retention_days)
    kept: List[Dict[str, object]] = []
    for row in rows:
        date_val = row.get("date")
        if not date_val:
            kept.append(row)
            continue
        try:
            d = dt.datetime.strptime(str(date_val), "%Y-%m-%d").date()
        except ValueError:
            kept.append(row)
            continue
        if d >= cutoff:
            kept.append(row)
    return kept


def main() -> int:
    args = parse_args()
    start = parse_date(args.from_date)
    end = parse_date(args.to_date)

    files = list_input_files(args.log_dir, args.include_meta)
    rows = read_rows(files, start, end)

    ensure_dir(args.output_dir)

    ai_events_headers = [
        "time",
        "schema_version",
        "event_id",
        "parent_event_id",
        "session_id",
        "date",
        "week",
        "hour",
        "weekday",
        "part_of_day",
        "is_weekend",
        "type",
        "event",
        "action",
        "is_human",
        "automation_guess",
        "source",
        "user_id",
        "user_name",
        "entity_id",
        "domain",
        "old_state",
        "new_state",
        "target_state",
        "state_after_delay",
        "delay_sec",
        "matched_target",
        "context_id",
        "parent_context_id",
        "is_state_event",
        "snapshot",
    ]

    ai_csv = os.path.join(args.output_dir, "ai_events.csv")
    write_csv(ai_csv, rows, ai_events_headers)

    daily_rows = build_daily_summary(rows)
    daily_csv = os.path.join(args.output_dir, "daily_summary.csv")
    write_csv(daily_csv, daily_rows, ["date", "user", "domain", "action", "count"])

    weekly_rows = build_weekly_summary(rows)
    weekly_csv = os.path.join(args.output_dir, "weekly_summary.csv")
    write_csv(weekly_csv, weekly_rows, ["week", "user", "domain", "action", "count"])

    if args.with_parquet:
        parquet_path = os.path.join(args.output_dir, "ai_events.parquet")
        write_parquet(parquet_path, rows)

    trainer_headers = [
        "time",
        "schema_version",
        "event_id",
        "session_id",
        "date",
        "week",
        "weekday",
        "hour",
        "part_of_day",
        "is_weekend",
        "user_id",
        "user_name",
        "entity_id",
        "domain",
        "action",
        "old_state",
        "new_state",
        "source",
        "automation_guess",
        "context_id",
        "parent_context_id",
        "snapshot",
    ]
    trainer_new_rows = build_trainer_rows(rows, args.trainer_include_automation_guess)
    trainer_csv = os.path.join(args.output_dir, "trainer_ready.csv")
    trainer_existing = load_csv_rows(trainer_csv)
    trainer_merged = merge_dedup(trainer_existing, trainer_new_rows)
    trainer_pruned = prune_by_days(trainer_merged, args.trainer_retention_days)
    write_csv(trainer_csv, trainer_pruned, trainer_headers)

    if args.with_parquet:
        trainer_parquet = os.path.join(args.output_dir, "trainer_ready.parquet")
        write_parquet(trainer_parquet, trainer_pruned)

    print(f"Input files: {len(files)}")
    print(f"Events exported: {len(rows)}")
    print(f"CSV: {ai_csv}")
    print(f"Daily summary: {daily_csv}")
    print(f"Weekly summary: {weekly_csv}")
    print(f"Trainer-ready CSV: {trainer_csv} (rows={len(trainer_pruned)})")
    if args.with_parquet:
        print(f"Parquet: {os.path.join(args.output_dir, 'ai_events.parquet')}")
        print(f"Trainer-ready Parquet: {os.path.join(args.output_dir, 'trainer_ready.parquet')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
