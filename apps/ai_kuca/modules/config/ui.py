def room_summary(room_cfg):
    rooms = list(room_cfg.keys()) if isinstance(room_cfg, dict) else []
    return f"Ucitane sobe: {', '.join(rooms) if rooms else 'nema soba'}"
