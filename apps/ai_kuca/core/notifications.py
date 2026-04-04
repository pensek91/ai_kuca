from ai_kuca.core.telegram_adapter import send_message as send_telegram_message


def send_missing_sensor_notifications(app, message, group_service, device_services):
    """Best-effort fanout to telegram + HA notify channels."""
    status = {
        "telegram": False,
        "group": False,
        "devices_sent": 0,
    }

    try:
        send_telegram_message(app, message, disable_formatting=True)
        status["telegram"] = True
    except Exception as ex:
        app.log(f"[ALERT] Telegram send failed: {ex}", level="WARNING")

    try:
        app.call_service(group_service, message=message)
        status["group"] = True
    except Exception as ex:
        app.log(f"[ALERT] Group notify failed: {ex}", level="WARNING")

    for svc in device_services or []:
        try:
            app.call_service(svc, message=message)
            status["devices_sent"] += 1
        except Exception:
            continue

    return status
