"""Port of ioBroker.mcdu ScratchpadManager.test.js and inputModeManager.test.js."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "mcdu"))

from input_engine import InputModeManager, Scratchpad  # noqa: E402


@pytest.fixture
def scratchpad():
    return Scratchpad()


@pytest.fixture
def manager(scratchpad):
    return InputModeManager(scratchpad)


# ---------------------------------------------------------------------------
# Scratchpad: content management
# ---------------------------------------------------------------------------


class TestScratchpadContent:
    def test_append_single_char(self, scratchpad):
        assert scratchpad.append("2") is True
        assert scratchpad.get_content() == "2"

    def test_append_sequence(self, scratchpad):
        for char in "22.5":
            scratchpad.append(char)
        assert scratchpad.get_content() == "22.5"

    def test_reject_when_full(self, scratchpad):
        scratchpad.content = "12345678901234567890"
        assert scratchpad.append("X") is False
        assert scratchpad.get_content() == "12345678901234567890"

    def test_special_characters(self, scratchpad):
        for char in "-10.5":
            scratchpad.append(char)
        assert scratchpad.get_content() == "-10.5"

    def test_append_resets_validation(self, scratchpad):
        scratchpad.set_valid(False, "ERROR")
        assert scratchpad.get_valid() is False
        scratchpad.append("2")
        assert scratchpad.get_valid() is True
        assert scratchpad.get_error_message() is None

    def test_clear_content(self, scratchpad):
        scratchpad.append("2")
        scratchpad.append("2")
        scratchpad.clear()
        assert scratchpad.get_content() == ""

    def test_clear_resets_validation(self, scratchpad):
        scratchpad.set_valid(False, "ERROR")
        scratchpad.clear()
        assert scratchpad.get_valid() is True
        assert scratchpad.get_error_message() is None

    def test_clear_resets_color(self, scratchpad):
        scratchpad.color = "red"
        scratchpad.clear()
        assert scratchpad.get_color() == "white"

    def test_set_from_string(self, scratchpad):
        scratchpad.set("21.0")
        assert scratchpad.get_content() == "21.0"

    def test_set_from_number(self, scratchpad):
        scratchpad.set(22.5)
        assert scratchpad.get_content() == "22.5"

    def test_set_color_amber(self, scratchpad):
        scratchpad.set("21.0")
        assert scratchpad.get_color() == "amber"

    def test_has_content(self, scratchpad):
        assert scratchpad.has_content() is False
        scratchpad.append("2")
        assert scratchpad.has_content() is True

    def test_get_display(self, scratchpad):
        assert scratchpad.get_display() == ""
        for char in "22.5":
            scratchpad.append(char)
        assert scratchpad.get_display() == "22.5"


class TestScratchpadColors:
    def test_default_white(self, scratchpad):
        assert scratchpad.get_color() == "white"

    def test_valid_green(self, scratchpad):
        scratchpad.set_valid(True)
        assert scratchpad.get_color() == "green"

    def test_invalid_red(self, scratchpad):
        scratchpad.set_valid(False, "ERROR")
        assert scratchpad.get_color() == "red"
        assert scratchpad.get_error_message() == "ERROR"


# ---------------------------------------------------------------------------
# Scratchpad: field validation
# ---------------------------------------------------------------------------


class TestNumericValidation:
    def test_valid_numeric(self, scratchpad):
        scratchpad.set("22.5")
        result = scratchpad.validate({"inputType": "numeric", "validation": {"min": 16, "max": 30}})
        assert result == {"valid": True, "error": None}

    def test_invalid_format(self, scratchpad):
        scratchpad.set("22.5.5")
        result = scratchpad.validate({"inputType": "numeric"})
        assert result["valid"] is False
        assert result["error"] == "UNGÜLTIGES FORMAT"

    def test_below_minimum(self, scratchpad):
        scratchpad.set("10")
        result = scratchpad.validate({"inputType": "numeric", "validation": {"min": 16, "max": 30}})
        assert result["error"] == "MINIMUM 16"

    def test_above_maximum(self, scratchpad):
        scratchpad.set("35")
        result = scratchpad.validate({"inputType": "numeric", "validation": {"min": 16, "max": 30}})
        assert result["error"] == "MAXIMUM 30"

    def test_step_valid(self, scratchpad):
        scratchpad.set("22.5")
        result = scratchpad.validate(
            {"inputType": "numeric", "validation": {"min": 16, "max": 30, "step": 0.5}}
        )
        assert result["valid"] is True

    def test_step_invalid(self, scratchpad):
        scratchpad.set("22.3")
        result = scratchpad.validate(
            {"inputType": "numeric", "validation": {"min": 16, "max": 30, "step": 0.5}}
        )
        assert result["error"] == "SCHRITT 0.5"

    def test_negative_numbers(self, scratchpad):
        scratchpad.set("-10.5")
        result = scratchpad.validate({"inputType": "numeric", "validation": {"min": -20, "max": 0}})
        assert result["valid"] is True

    def test_zero(self, scratchpad):
        scratchpad.set("0")
        result = scratchpad.validate({"inputType": "numeric", "validation": {"min": 0, "max": 100}})
        assert result["valid"] is True

    def test_small_steps_floating_point(self, scratchpad):
        scratchpad.set("22.05")
        result = scratchpad.validate(
            {"inputType": "numeric", "validation": {"min": 0, "max": 100, "step": 0.05}}
        )
        assert result["valid"] is True

    @pytest.mark.parametrize("value", ["22.5.5", ".", "22.", ".5", "1e5", "0123"])
    def test_numeric_format_edge_cases_invalid(self, scratchpad, value):
        assert scratchpad.validate_numeric_format(value)["valid"] is False

    @pytest.mark.parametrize("value", ["22", "22.5", "-22.5", "0", "-0", "-"])
    def test_numeric_format_edge_cases_valid(self, scratchpad, value):
        assert scratchpad.validate_numeric_format(value)["valid"] is True


class TestOtherValidation:
    def test_time_valid(self, scratchpad):
        scratchpad.set("08:30")
        assert scratchpad.validate({"inputType": "time"})["valid"] is True

    def test_time_invalid(self, scratchpad):
        scratchpad.set("25:99")
        result = scratchpad.validate({"inputType": "time"})
        assert result["error"] == "FORMAT: HH:MM"

    def test_time_non_time(self, scratchpad):
        scratchpad.set("hello")
        assert scratchpad.validate({"inputType": "time"})["valid"] is False

    def test_text_within_limit(self, scratchpad):
        scratchpad.set("Hello World")
        result = scratchpad.validate({"inputType": "text", "validation": {"maxLength": 20}})
        assert result["valid"] is True

    def test_text_exceeds_limit(self, scratchpad):
        scratchpad.set("This is a very long text that exceeds the limit")
        result = scratchpad.validate({"inputType": "text", "validation": {"maxLength": 20}})
        assert result["error"] == "MAX 20 ZEICHEN"

    def test_text_pattern_valid(self, scratchpad):
        scratchpad.set("ABC123")
        result = scratchpad.validate({"inputType": "text", "validation": {"pattern": "^[A-Z0-9]+$"}})
        assert result["valid"] is True

    def test_text_pattern_invalid(self, scratchpad):
        scratchpad.set("abc123")
        result = scratchpad.validate({"inputType": "text", "validation": {"pattern": "^[A-Z0-9]+$"}})
        assert result["error"] == "UNGÜLTIGES FORMAT"

    def test_required_empty(self, scratchpad):
        scratchpad.clear()
        result = scratchpad.validate({"inputType": "text", "validation": {"required": True}})
        assert result["error"] == "PFLICHTFELD"

    def test_not_required_empty(self, scratchpad):
        scratchpad.clear()
        result = scratchpad.validate({"inputType": "text", "validation": {"required": False}})
        assert result["valid"] is True

    def test_select_valid(self, scratchpad):
        scratchpad.set("AUTO")
        result = scratchpad.validate(
            {"inputType": "select", "validation": {"options": ["AUTO", "HEAT", "OFF"]}}
        )
        assert result["valid"] is True

    def test_select_invalid(self, scratchpad):
        scratchpad.set("TURBO")
        result = scratchpad.validate(
            {"inputType": "select", "validation": {"options": ["AUTO", "HEAT", "OFF"]}}
        )
        assert result["error"] == "UNGÜLTIGE AUSWAHL"

    def test_empty_config(self, scratchpad):
        scratchpad.set("anything")
        assert scratchpad.validate({})["valid"] is True

    def test_null_config(self, scratchpad):
        scratchpad.set("anything")
        assert scratchpad.validate(None)["valid"] is True


# ---------------------------------------------------------------------------
# Scratchpad: Airbus error pattern
# ---------------------------------------------------------------------------


class TestAirbusErrorPattern:
    def test_show_error_saves_content(self, scratchpad):
        scratchpad.set("22.5")
        scratchpad.show_error("FORMAT ERROR")
        assert scratchpad.get_content() == "FORMAT ERROR"
        assert scratchpad.saved_content == "22.5"
        assert scratchpad.error_showing is True
        assert scratchpad.get_color() == "white"

    def test_first_clr_restores(self, scratchpad):
        scratchpad.set("999")
        scratchpad.show_error("ENTRY OUT OF RANGE")
        scratchpad.clear()
        assert scratchpad.get_content() == "999"
        assert scratchpad.error_showing is False
        assert scratchpad.saved_content is None

    def test_second_clr_clears(self, scratchpad):
        scratchpad.set("999")
        scratchpad.show_error("ENTRY OUT OF RANGE")
        scratchpad.clear()
        scratchpad.clear()
        assert scratchpad.get_content() == ""

    def test_normal_clear_without_error(self, scratchpad):
        scratchpad.set("22.5")
        scratchpad.clear()
        assert scratchpad.get_content() == ""
        assert scratchpad.saved_content is None


# ---------------------------------------------------------------------------
# InputModeManager: modes and keys
# ---------------------------------------------------------------------------


class TestModeManagement:
    def test_starts_normal(self, manager):
        assert manager.get_mode() == "normal"

    def test_first_key_enters_input_mode(self, manager):
        assert manager.handle_key_input("2") == ("render",)
        assert manager.get_mode() == "input"
        assert manager.scratchpad.get_content() == "2"

    def test_stays_in_input_mode(self, manager):
        manager.handle_key_input("2")
        manager.handle_key_input("5")
        assert manager.get_mode() == "input"
        assert manager.scratchpad.get_content() == "25"

    def test_full_scratchpad_reports_once(self, manager):
        manager.scratchpad.content = "1" * 20
        manager.mode = "input"
        assert manager.handle_key_input("X") == ("full",)
        assert manager.handle_key_input("X") == ("none",)

    def test_plusminus_empty_inserts_minus(self, manager):
        assert manager.handle_plusminus() == ("render",)
        assert manager.scratchpad.get_content() == "-"

    def test_plusminus_toggles_sign(self, manager):
        manager.handle_key_input("5")
        manager.handle_plusminus()
        assert manager.scratchpad.get_content() == "-5"
        manager.handle_plusminus()
        assert manager.scratchpad.get_content() == "5"


class TestClr:
    def test_clear_scratchpad_first(self, manager):
        manager.handle_key_input("5")
        assert manager.handle_clr(now=10.0, has_parent=True) == ("cleared",)
        assert manager.scratchpad.get_content() == ""
        assert manager.get_mode() == "normal"

    def test_parent_navigation_when_empty(self, manager):
        assert manager.handle_clr(now=10.0, has_parent=True) == ("parent",)

    def test_none_without_parent(self, manager):
        assert manager.handle_clr(now=10.0, has_parent=False) == ("none",)

    def test_double_clr_goes_home(self, manager):
        manager.handle_clr(now=10.0, has_parent=True)
        assert manager.handle_clr(now=10.5, has_parent=True) == ("home",)

    def test_slow_second_clr_is_not_double(self, manager):
        manager.handle_clr(now=10.0, has_parent=True)
        assert manager.handle_clr(now=11.5, has_parent=True) == ("parent",)

    def test_clr_restores_rejected_input_first(self, manager):
        manager.scratchpad.set("999")
        manager.scratchpad.show_error("ENTRY OUT OF RANGE")
        assert manager.handle_clr(now=10.0, has_parent=True) == ("cleared",)
        assert manager.scratchpad.get_content() == "999"


# ---------------------------------------------------------------------------
# InputModeManager: LSK (metadata-driven)
# ---------------------------------------------------------------------------


def _line(display=None, button=None, side="left"):
    side_config = {
        "label": "",
        "display": display or {"type": "empty"},
        "button": button or {"type": "empty"},
    }
    other = {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}}
    return {
        "row": 3,
        "left": side_config if side == "left" else other,
        "right": other if side == "left" else side_config,
    }


DP_DISPLAY = {"type": "datapoint", "text": "TEMP", "source": "number.target"}


class TestLskDatapoint:
    def test_toggle_boolean(self, manager):
        line = _line(display={"type": "datapoint", "source": "switch.light"})
        meta = lambda s: {"write": True, "type": "boolean"}
        assert manager.handle_lsk(line, "left", meta) == ("toggle", "switch.light")

    def test_toggle_regardless_of_scratchpad(self, manager):
        manager.handle_key_input("5")
        line = _line(display={"type": "datapoint", "source": "switch.light"})
        meta = lambda s: {"write": True, "type": "boolean"}
        assert manager.handle_lsk(line, "left", meta) == ("toggle", "switch.light")

    def test_write_number(self, manager):
        for char in "21.5":
            manager.handle_key_input(char)
        meta = lambda s: {"write": True, "type": "number", "min": 16, "max": 30}
        result = manager.handle_lsk(_line(display=DP_DISPLAY), "left", meta)
        assert result == ("write", "number.target", 21.5)
        assert manager.scratchpad.get_content() == ""
        assert manager.get_mode() == "normal"

    def test_format_error(self, manager):
        for char in "2.5.5":
            manager.handle_key_input(char)
        meta = lambda s: {"write": True, "type": "number"}
        result = manager.handle_lsk(_line(display=DP_DISPLAY), "left", meta)
        assert result == ("error", "FORMAT ERROR")
        assert manager.scratchpad.get_content() == "FORMAT ERROR"
        assert manager.scratchpad.saved_content == "2.5.5"

    def test_below_min_out_of_range(self, manager):
        manager.handle_key_input("5")
        meta = lambda s: {"write": True, "type": "number", "min": 16, "max": 30}
        result = manager.handle_lsk(_line(display=DP_DISPLAY), "left", meta)
        assert result == ("error", "ENTRY OUT OF RANGE")

    def test_above_max_out_of_range(self, manager):
        for char in "35":
            manager.handle_key_input(char)
        meta = lambda s: {"write": True, "type": "number", "min": 16, "max": 30}
        result = manager.handle_lsk(_line(display=DP_DISPLAY), "left", meta)
        assert result == ("error", "ENTRY OUT OF RANGE")

    def test_empty_scratchpad_number_does_nothing(self, manager):
        meta = lambda s: {"write": True, "type": "number"}
        assert manager.handle_lsk(_line(display=DP_DISPLAY), "left", meta) == ("none",)

    def test_write_string(self, manager):
        for char in "ABC":
            manager.handle_key_input(char)
        display = {"type": "datapoint", "source": "input_text.note"}
        meta = lambda s: {"write": True, "type": "string"}
        result = manager.handle_lsk(_line(display=display), "left", meta)
        assert result == ("write", "input_text.note", "ABC")

    def test_select_options_rejected(self, manager):
        for char in "TURBO":
            manager.handle_key_input(char)
        display = {"type": "datapoint", "source": "select.mode"}
        meta = lambda s: {"write": True, "type": "string", "options": ["AUTO", "HEAT"]}
        result = manager.handle_lsk(_line(display=display), "left", meta)
        assert result == ("error", "UNGUELTIGE AUSWAHL")

    def test_read_only_shows_error(self, manager):
        display = {"type": "datapoint", "source": "sensor.temp"}
        meta = lambda s: {"write": False, "type": "number"}
        result = manager.handle_lsk(_line(display=display), "left", meta)
        assert result == ("error", "SCHREIBGESCHUETZT")
        assert manager.scratchpad.get_content() == "SCHREIBGESCHUETZT"

    def test_no_metadata_does_nothing(self, manager):
        result = manager.handle_lsk(_line(display=DP_DISPLAY), "left", lambda s: None)
        assert result == ("none",)


class TestLskButtons:
    def test_navigation_button_action(self, manager):
        button = {"type": "navigation", "action": "goto", "target": "lights"}
        result = manager.handle_lsk(_line(button=button), "left", lambda s: None)
        assert result == ("action", button)

    def test_datapoint_button_without_target_not_actionable(self, manager):
        button = {"type": "datapoint", "target": ""}
        result = manager.handle_lsk(_line(button=button), "left", lambda s: None)
        assert result == ("none",)

    def test_display_datapoint_preferred_over_stale_button(self, manager):
        button = {"type": "datapoint", "target": "switch.old"}
        line = _line(display={"type": "datapoint", "source": "switch.new"}, button=button)
        meta = lambda s: {"write": True, "type": "boolean"}
        assert manager.handle_lsk(line, "left", meta) == ("toggle", "switch.new")

    def test_is_actionable_button(self, manager):
        assert manager.is_actionable_button({"type": "navigation", "target": ""}) is False
        assert manager.is_actionable_button({"type": "navigation", "target": "x"}) is True
        assert manager.is_actionable_button({"type": "empty"}) is False
        assert manager.is_actionable_button(None) is False

    def test_right_side(self, manager):
        button = {"type": "navigation", "target": "lights"}
        line = _line(button=button, side="right")
        assert manager.handle_lsk(line, "right", lambda s: None) == ("action", button)

    def test_get_state(self, manager):
        manager.handle_key_input("7")
        state = manager.get_state()
        assert state["mode"] == "input"
        assert state["scratchpad_content"] == "7"
        assert state["scratchpad_valid"] is True
