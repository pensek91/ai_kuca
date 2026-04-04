def _escape_markdown_v2(text):
    # Escape Telegram MarkdownV2 special chars to keep message content literal.
    special = "_[]()~`>#+-=|{}.!"
    out = []
    for ch in str(text or ""):
        if ch in special:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def send_message(app, message, disable_formatting=True):
    payload = {"message": str(message or "")}
    if disable_formatting:
        payload["message"] = _escape_markdown_v2(payload["message"])
        payload["parse_mode"] = "MarkdownV2"
    app.call_service("telegram_bot/send_message", **payload)
