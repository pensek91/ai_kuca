import time
from datetime import datetime, timezone


def push_log_to_ha(app, message, level, sensor_entity, history_seconds, max_items):
    """
    Šalje log poruku u HA senzor i održava povijest.
    
    Ažurira stanje senzora s novom porukom i dodaje je u history listu,
    čisteći stare unose po vremenu i maksimalnom broju.
    
    Args:
        app: AppDaemon app instanca.
        message (str): Log poruka.
        level (str): Razina loga (INFO, DEBUG, itd.).
        sensor_entity (str): HA entitet senzora za log.
        history_seconds (int): Koliko sekundi povijesti čuvati.
        max_items (int): Maksimalni broj stavki u povijesti.
    """
    try:
        now = time.time()
        now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        history = []
        data = app.get_state(sensor_entity, attribute="all")
        if isinstance(data, dict):
            attrs = data.get("attributes") or {}
            history = attrs.get("history") or []

        # normalize history
        norm = []
        for item in history:
            if not isinstance(item, dict):
                continue
            ts = item.get("ts") or item.get("time")
            msg = item.get("msg") or item.get("message")
            lvl = item.get("level") or "INFO"
            if ts is None or msg is None:
                continue
            norm.append({"ts": ts, "level": lvl, "msg": msg})

        # append new
        norm.append({"ts": now_iso, "level": level, "msg": message})

        # prune by age
        pruned = []
        cutoff = now - history_seconds
        for item in norm:
            try:
                ts = datetime.fromisoformat(item["ts"].replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = now
            if ts >= cutoff:
                pruned.append(item)

        # keep last max_items
        if len(pruned) > max_items:
            pruned = pruned[-max_items:]

        app.set_state(
            sensor_entity,
            state=message,
            attributes={
                "last_level": level,
                "last_ts": now_iso,
                "history": pruned,
            },
        )
    except Exception:
        # don't let logging failures break apps
        return
