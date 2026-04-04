def ensure_ui_helpers(app):
    """Ensure all HA helpers from HA_helpers.yaml exist."""
    helpers = []

    for entity_id in [
        app.ai_heating_active,
        app.ai_heating_eco,
        app.ai_kuca_reload_config,
        app.ai_kuca_generate_config,
        app.ai_kuca_room_builder_generate,
        app.ai_kuca_room_builder_delete,
    ]:
        helpers.append(
            {
                "entity_id": entity_id,
                "service": "input_boolean/create",
                "name": entity_id.split(".")[1].replace("_", " ").title(),
            }
        )

    for entity_id in [
        app.ai_kuca_system_config,
        app.ai_kuca_room_config,
        app.ai_kuca_room_builder_name,
        app.ai_kuca_room_builder_target,
        app.ai_kuca_room_builder_windows,
        app.ai_kuca_outdoor_temp_sensors,
        app.ai_kuca_climate_entities,
    ]:
        helpers.append(
            {
                "entity_id": entity_id,
                "service": "input_text/create",
                "name": entity_id.split(".")[1].replace("_", " ").title(),
                "initial": "",
            }
        )

    helpers.append(
        {
            "entity_id": app.ai_kuca_config_mode,
            "service": "input_select/create",
            "name": app.ai_kuca_config_mode.split(".")[1].replace("_", " ").title(),
            "options": ["-- Odaberi --", "System Config", "Room Config"],
        }
    )

    for entity_id in [
        app.ai_kuca_room_select,
        app.ai_kuca_heating_flow_sensor,
        app.ai_kuca_heating_boiler_sensor,
        app.ai_kuca_heating_outdoor_sensor,
        app.ai_kuca_heating_active_switch,
        app.ai_kuca_heating_eco_switch,
        app.ai_kuca_heating_overheat_switch,
        app.ai_kuca_pump_switch,
        app.ai_kuca_valve_pause,
        app.ai_kuca_valve_open,
        app.ai_kuca_valve_close,
        app.ai_kuca_flow_sensor_2,
        app.ai_kuca_target_sensor,
        app.ai_kuca_room_builder_climate,
        app.ai_kuca_room_builder_temp_sensor,
        app.ai_kuca_room_builder_humidity_sensor,
        app.ai_kuca_room_builder_fan,
        app.boost_soba,
        app.turbo_boost_duration,
        app.ai_kuca_boost_select,
        app.ai_kuca_duration_select,
    ]:
        helpers.append(
            {
                "entity_id": entity_id,
                "service": "input_select/create",
                "name": entity_id.split(".")[1].replace("_", " ").title(),
                "options": ["<izaberi>"],
            }
        )

    for entity_id in app.input_numbers:
        helpers.append(
            {
                "entity_id": entity_id,
                "service": "input_number/create",
                "name": entity_id.split(".")[1].replace("_", " ").title(),
            }
        )

    for helper in helpers:
        if app.get_state(helper["entity_id"]) is not None:
            continue
        try:
            app.call_service(
                helper["service"],
                entity_id=helper["entity_id"],
                name=helper.get("name"),
                initial=helper.get("initial"),
                options=helper.get("options"),
            )
            app.log(f"[CONFIG] Created helper {helper['entity_id']} via {helper['service']}", level="DEBUG")
        except Exception as ex:
            app.log(f"[CONFIG] Unable to create helper {helper['entity_id']}: {ex}", level="WARNING")


def show_current_config(app):
    try:
        system_cfg = app.load_yaml_file("system_configs.yaml") or {}
        room_cfg = app.load_yaml_file("room_configs.yaml") or {}
        rooms = list(room_cfg.keys()) if room_cfg else []
        summary_text = f"Ucitane sobe: {', '.join(rooms) if rooms else 'nema soba'}"
        system_status = "System config: OK" if system_cfg else "System config: EMPTY"
        app.log(f"[CONFIG] {system_status} | {summary_text}", level="INFO")
    except Exception as ex:
        app.log(f"[CONFIG] Greska pri ucitavanju config datoteka: {ex}", level="WARNING")


def update_ui_select_options(app):
    entities = app.get_state() or {}
    sensors = sorted([e for e in entities.keys() if e.startswith("sensor.")])
    switches = sorted([e for e in entities.keys() if e.startswith("switch.")])
    input_bools = sorted([e for e in entities.keys() if e.startswith("input_boolean.")])

    select_mapping = {
        app.select_flow_sensor: sensors,
        app.select_boiler_sensor: sensors,
        app.select_active_switch: input_bools,
        app.select_eco_switch: input_bools,
        app.select_overheat_switch: input_bools,
        app.select_pump_switch: switches,
        app.room_builder_climate: [e for e in entities.keys() if e.startswith("climate.")],
        app.room_builder_temp_sensor: sensors,
        app.room_builder_humidity_sensor: sensors,
        app.room_builder_fan: [e for e in entities.keys() if e.startswith("fan.")],
    }

    for entity_id, options in select_mapping.items():
        if app.get_state(entity_id) is None:
            continue
        try:
            app.call_service("input_select/set_options", entity_id=entity_id, options=options)
        except Exception as ex:
            app.log(f"[CONFIG] Unable to update options for {entity_id}: {ex}", level="WARNING")


def populate_all_dropdowns(app):
    app.log("[CONFIG] Pokrenuta _populate_all_dropdowns()", level="INFO")
    entities = app.get_state() or {}

    sensors = sorted([e for e in entities.keys() if e.startswith("sensor.")])
    switches = sorted([e for e in entities.keys() if e.startswith("switch.")])
    climate = sorted([e for e in entities.keys() if e.startswith("climate.")])
    fans = sorted([e for e in entities.keys() if e.startswith("fan.")])
    input_bools = sorted([e for e in entities.keys() if e.startswith("input_boolean.")])

    app.log(
        f"[CONFIG] Pronadeni entiteti: sensors={len(sensors)}, switches={len(switches)}, climate={len(climate)}, fans={len(fans)}, input_bools={len(input_bools)}",
        level="INFO",
    )

    options_map = {
        app.select_flow_sensor: ["NONE"] + sensors,
        app.select_boiler_sensor: ["NONE"] + sensors,
        app.select_active_switch: ["NONE"] + input_bools,
        app.select_eco_switch: ["NONE"] + input_bools,
        app.select_overheat_switch: ["NONE"] + input_bools,
        app.select_pump_switch: ["NONE"] + switches,
        app.select_valve_pause: ["NONE"] + input_bools,
        app.select_valve_open: ["NONE"] + switches,
        app.select_valve_close: ["NONE"] + switches,
        app.select_flow_sensor_2: ["NONE"] + sensors,
        app.select_target_sensor: ["NONE"] + sensors,
        app.room_builder_climate: ["NONE"] + climate,
        app.room_builder_temp_sensor: ["NONE"] + sensors,
        app.room_builder_humidity_sensor: ["NONE"] + sensors,
        app.room_builder_fan: ["NONE"] + fans,
    }

    for entity_id, options in options_map.items():
        try:
            app.call_service("input_select/set_options", entity_id=entity_id, options=options)
            app.log(f"[CONFIG] Popunjeni {entity_id} sa {len(options)} opcija", level="INFO")
        except Exception as ex:
            app.log(f"[CONFIG] Greska pri popunjavanju {entity_id}: {ex}", level="WARNING")


def load_system_config_values(app):
    app.log("[CONFIG] Pokrenuta _load_system_config_values()", level="INFO")
    room_cfg = app.load_yaml_file("room_configs.yaml") or {}
    rooms = list(room_cfg.keys()) if room_cfg else []
    room_options = ["NONE"] + sorted(rooms)

    app.log(f"[CONFIG] Dostupne sobe: {rooms}", level="INFO")
    try:
        app.call_service("input_select/set_options", entity_id=app.room_select, options=room_options)
        app.log(f"[CONFIG] Popunjeni room_select sa {len(room_options)} opcija", level="INFO")
    except Exception as ex:
        app.log(f"[CONFIG] Greska pri postavljanju room_select opcija: {ex}", level="WARNING")

    system_cfg = app.load_yaml_file("system_configs.yaml") or {}
    heating = system_cfg.get("heating_main", {}) or {}
    pump = system_cfg.get("pump", {}) or {}
    overheat = system_cfg.get("overheat", {}) or {}
    valve_control = system_cfg.get("valve_control", {}) or {}

    app.log("[CONFIG] Ucitano iz system_configs.yaml: heating, pump, overheat, valve_control sekcije", level="INFO")

    dropdown_map = {
        app.select_flow_sensor: heating.get("flow_sensor", "NONE"),
        app.select_boiler_sensor: heating.get("boiler_sensor", "NONE"),
        app.select_active_switch: heating.get("active_switch", "NONE"),
        app.select_eco_switch: heating.get("eco_switch", "NONE"),
        app.select_overheat_switch: heating.get("overheat_switch", "NONE"),
        app.select_pump_switch: pump.get("pump_switch", "NONE"),
        app.select_valve_pause: overheat.get("valve_pause", "NONE"),
        app.select_valve_open: overheat.get("valve_open", "NONE"),
        app.select_valve_close: valve_control.get("valve_close", "NONE"),
        app.select_flow_sensor_2: valve_control.get("flow_sensor_2", "NONE"),
        app.select_target_sensor: valve_control.get("target_sensor", "NONE"),
    }

    for entity_id, value in dropdown_map.items():
        try:
            app.set_state(entity_id, state=value if value and value != "NONE" else "NONE")
            app.log(f"[CONFIG] Postavio {entity_id} = {value}", level="INFO")
        except Exception as ex:
            app.log(f"[CONFIG] Greska pri postavljanju {entity_id}: {ex}", level="WARNING")

    outdoor_sensors = heating.get("outdoor_temp_sensors", []) or []
    if outdoor_sensors and isinstance(outdoor_sensors, list):
        outdoor_sensors_str = ", ".join(outdoor_sensors)
        try:
            app.set_state(app.outdoor_temp_sensors_text, state=outdoor_sensors_str)
            app.log(f"[CONFIG] Postavio outdoor_temp_sensors = {outdoor_sensors_str}", level="INFO")
        except Exception as ex:
            app.log(f"[CONFIG] Greska pri postavljanju outdoor_temp_sensors: {ex}", level="WARNING")

    predictive = system_cfg.get("predictive", {}) or {}
    ventilation = system_cfg.get("ventilation", {}) or {}

    def set_number(entity_id, value):
        if value is not None:
            try:
                app.set_state(entity_id, state=str(value))
            except Exception as ex:
                app.log(f"[CONFIG] Greska pri postavljanju {entity_id}: {ex}", level="WARNING")

    set_number(app.param_max_room_temp, heating.get("max_room_temp"))
    set_number(app.param_min_room_temp, heating.get("min_room_temp"))
    set_number(app.param_eco_delta, heating.get("eco_delta"))

    set_number(app.param_overheat_loop_interval, overheat.get("main_loop_interval"))
    set_number(app.param_stage1_on, overheat.get("stage1_on"))
    set_number(app.param_stage1_off, overheat.get("stage1_off"))
    set_number(app.param_stage2_on, overheat.get("stage2_on"))
    set_number(app.param_stage2_off, overheat.get("stage2_off"))

    set_number(app.param_valve_start_delay, valve_control.get("start_delay"))
    set_number(app.param_valve_deadband, valve_control.get("deadband"))
    set_number(app.param_valve_min_pulse, valve_control.get("min_base_pulse"))
    set_number(app.param_valve_max_pulse, valve_control.get("max_base_pulse"))
    set_number(app.param_valve_max_error, valve_control.get("max_error"))
    set_number(app.param_pump_start_delay, valve_control.get("pump_start_delay"))
    set_number(app.param_pump_off_delay, valve_control.get("pump_off_delay"))
    set_number(app.param_pump_cooldown, valve_control.get("cooldown_after_pulse"))

    set_number(app.param_pump_min_on, pump.get("min_on_seconds"))
    set_number(app.param_pump_min_off, pump.get("min_off_seconds"))
    set_number(app.param_pump_loop_interval, pump.get("main_loop_interval"))

    set_number(app.param_pred_window_short, predictive.get("window_short_minutes"))
    set_number(app.param_pred_window_long, predictive.get("window_long_minutes"))
    set_number(app.param_pred_min_points_short, predictive.get("min_points_short"))
    set_number(app.param_pred_min_points_long, predictive.get("min_points_long"))
    set_number(app.param_pred_loss_coeff, predictive.get("loss_coeff_default"))
    set_number(app.param_pred_window_mult, predictive.get("window_loss_multiplier"))
    set_number(app.param_pred_weight_short, predictive.get("weight_short"))
    set_number(app.param_pred_weight_long, predictive.get("weight_long"))

    set_number(app.param_vent_delta_on, ventilation.get("delta_on"))
    set_number(app.param_vent_delta_off, ventilation.get("delta_off"))
    set_number(app.param_vent_abs_on, ventilation.get("abs_on"))
    set_number(app.param_vent_abs_off, ventilation.get("abs_off"))
    set_number(app.param_vent_min_on_sec, ventilation.get("min_on_sec"))
    set_number(app.param_vent_min_off_sec, ventilation.get("min_off_sec"))
    set_number(app.param_vent_outdoor_max, ventilation.get("outdoor_humidity_max"))
    set_number(app.param_vent_interval, ventilation.get("interval_sec"))

    app.log("[CONFIG] Ucitane sve vrijednosti iz system_configs.yaml", level="INFO")


def on_config_mode_changed(app, new):
    mode = (str(new) or "").strip().lower()
    app.log(f"[CONFIG] config_mode promijenjeno: mode='{mode}' (raw='{new}')", level="INFO")

    if mode == "room config":
        app.log("[CONFIG] Room Config mode odabran - ucitavanje soba", level="INFO")
        room_cfg = app.load_yaml_file("room_configs.yaml") or {}
        rooms = list(room_cfg.keys()) if room_cfg else []
        options = ["NONE"] + sorted(rooms)
        try:
            app.call_service("input_select/set_options", entity_id=app.room_select, options=options)
            app.log(f"[CONFIG] Popunjene dostupne sobe: {rooms}", level="INFO")
        except Exception as ex:
            app.log(f"[CONFIG] Greska pri popunjavanju room_select: {ex}", level="WARNING")
        app._run_ui_manager_phase("mode_change_room", force=True)
        return

    if mode == "system config":
        app.log("[CONFIG] System Config mode odabran - ucitavanje vrijednosti", level="INFO")
        app.set_state(app.room_select, state="NONE")
        app._run_ui_manager_phase("mode_change_system", force=True)
        return

    app.log(f"[CONFIG] Nepoznat mode: '{mode}' - nece se nista ucitati", level="WARNING")


def on_room_selected(app, new):
    room_name = (str(new) or "").strip()

    if room_name == "NONE" or not room_name:
        app.set_state(app.room_builder_name, state="")
        app.set_state(app.room_builder_target, state="21.0")
        app.set_state(app.room_builder_climate, state="NONE")
        app.set_state(app.room_builder_temp_sensor, state="NONE")
        app.set_state(app.room_builder_humidity_sensor, state="NONE")
        app.set_state(app.room_builder_fan, state="NONE")
        app.set_state(app.room_builder_window_sensors, state="")
        return

    room_cfg = app.load_yaml_file("room_configs.yaml") or {}
    room_data = room_cfg.get(room_name, {})

    try:
        app.set_state(app.room_builder_name, state=room_name)

        target_input = room_data.get("target_input")
        target = None
        if isinstance(target_input, str) and target_input:
            target = app.get_state(target_input)
        if target in (None, "", "unknown", "unavailable"):
            target = room_data.get("target", "21.0")
        app.set_state(app.room_builder_target, state=str(target))

        climate = room_data.get("climate", "NONE")
        app.set_state(app.room_builder_climate, state=climate if climate else "NONE")

        temp_sensor = room_data.get("temp_sensor", "NONE")
        app.set_state(app.room_builder_temp_sensor, state=temp_sensor if temp_sensor else "NONE")

        humidity_sensor = room_data.get("humidity_sensor", "NONE")
        app.set_state(app.room_builder_humidity_sensor, state=humidity_sensor if humidity_sensor else "NONE")

        fan = room_data.get("fan", "NONE")
        app.set_state(app.room_builder_fan, state=fan if fan else "NONE")

        windows = room_data.get("window_sensors", [])
        windows_str = ", ".join(windows) if isinstance(windows, list) else ""
        app.set_state(app.room_builder_window_sensors, state=windows_str)

        app.log(f"[CONFIG] Ucitani podaci sobe '{room_name}'", level="INFO")
    except Exception as ex:
        app.log(f"[CONFIG] Greska pri ucitavanju podataka sobe: {ex}", level="WARNING")
