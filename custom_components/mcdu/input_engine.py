"""Pure-Python input engine: scratchpad and input-mode state machine.

Port of ioBroker.mcdu lib/input/ScratchpadManager.js and InputModeManager.js.
Behavior is specified by the mocha suites of that repository, mirrored in
tests/test_input_engine.py.

No Home Assistant imports. The state machine returns *decisions* (small
tuples) instead of performing side effects; the controller executes them
(writes entities, navigates, renders). This keeps the aviation input logic
synchronous and fully unit-testable.

German UI strings are intentional (project convention).
"""

from __future__ import annotations

import re
from typing import Any

MAX_SCRATCHPAD_LENGTH = 20
DOUBLE_CLR_WINDOW = 1.0  # seconds

_TIME_RE = re.compile(r"^([0-1][0-9]|2[0-3]):([0-5][0-9])$")
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")
_LEADING_ZEROS_RE = re.compile(r"^-?0\d+")


class Scratchpad:
    """Line-14 input buffer with Airbus-style error recovery."""

    def __init__(self) -> None:
        self.content = ""
        self.is_valid = True
        self.error_message: str | None = None
        self.color = "white"
        self.max_length = MAX_SCRATCHPAD_LENGTH
        self.placeholder = ""
        self.full_error_showing = False
        self.saved_content: str | None = None
        self.error_showing = False

    # -- content -------------------------------------------------------

    def append(self, char: str) -> bool:
        if len(self.content) >= self.max_length:
            return False
        self.content += char
        self.is_valid = True
        self.color = "white"
        self.error_message = None
        return True

    def clear(self) -> None:
        """Airbus pattern: first CLR after an error restores the rejected
        input for editing; the second CLR clears for real."""
        if self.error_showing and self.saved_content is not None:
            self.content = self.saved_content
            self.saved_content = None
            self.error_showing = False
            self.is_valid = True
            self.color = "white"
            self.error_message = None
            self.full_error_showing = False
            return

        self.content = ""
        self.is_valid = True
        self.color = "white"
        self.error_message = None
        self.full_error_showing = False
        self.saved_content = None
        self.error_showing = False

    def set(self, value: Any) -> None:
        """Set content from a copied value (amber = editing existing value)."""
        self.content = str(value)
        self.is_valid = True
        self.color = "amber"
        self.error_message = None

    def get_content(self) -> str:
        return self.content

    def has_content(self) -> bool:
        return len(self.content) > 0

    def get_display(self) -> str:
        return self.content if self.content else self.placeholder

    def get_color(self) -> str:
        return self.color

    # -- validation state ---------------------------------------------

    def set_valid(self, is_valid: bool, error_message: str | None = None) -> None:
        self.is_valid = is_valid
        self.error_message = error_message
        self.color = "green" if is_valid else "red"

    def get_valid(self) -> bool:
        return self.is_valid

    def get_error_message(self) -> str | None:
        return self.error_message

    def show_error(self, message: str) -> None:
        """Show an error in the scratchpad, saving current content for CLR."""
        self.saved_content = self.content
        self.content = message
        self.error_showing = True
        self.is_valid = False
        self.color = "white"  # Airbus: errors show in white
        self.error_message = message

    # -- field validation ----------------------------------------------

    def validate(self, field_config: dict | None) -> dict:
        """Validate content against a field config → {valid, error}."""
        if not field_config:
            return {"valid": True, "error": None}

        value = self.content
        rules = field_config.get("validation") or {}
        input_type = field_config.get("inputType") or "text"

        if rules.get("required") and not value:
            return {"valid": False, "error": "PFLICHTFELD"}
        if not value:
            return {"valid": True, "error": None}

        if input_type == "numeric":
            format_result = self.validate_numeric_format(value)
            if not format_result["valid"]:
                return format_result

            num = float(value) if value != "-" else 0.0
            if (minimum := rules.get("min")) is not None and num < minimum:
                return {"valid": False, "error": f"MINIMUM {_fmt_num(minimum)}"}
            if (maximum := rules.get("max")) is not None and num > maximum:
                return {"valid": False, "error": f"MAXIMUM {_fmt_num(maximum)}"}
            if (step := rules.get("step")) is not None:
                remainder = (num - (rules.get("min") or 0)) % step
                tolerance = min(step * 0.01, 0.001)
                if abs(remainder) > tolerance and abs(remainder - step) > tolerance:
                    return {"valid": False, "error": f"SCHRITT {_fmt_num(step)}"}
        elif input_type == "time":
            if not _TIME_RE.match(value):
                return {"valid": False, "error": "FORMAT: HH:MM"}
        elif input_type == "text":
            if (max_length := rules.get("maxLength")) and len(value) > max_length:
                return {"valid": False, "error": f"MAX {max_length} ZEICHEN"}
            if (pattern := rules.get("pattern")) and not re.search(pattern, value):
                return {"valid": False, "error": "UNGÜLTIGES FORMAT"}
        elif input_type == "select":
            options = rules.get("options")
            if isinstance(options, list) and value not in options:
                return {"valid": False, "error": "UNGÜLTIGE AUSWAHL"}

        return {"valid": True, "error": None}

    def validate_numeric_format(self, value: str) -> dict:
        """Strict numeric format: no double dots, no exponents, no leading
        zeros, no dangling dots. A lone '-' is a valid intermediate state."""
        invalid = {"valid": False, "error": "UNGÜLTIGES FORMAT"}
        if value.count(".") > 1:
            return invalid
        if "e" in value or "E" in value:
            return invalid
        if _LEADING_ZEROS_RE.match(value):
            return invalid
        if not _NUMERIC_RE.match(value):
            if value == "-":
                return {"valid": True, "error": None}
            return invalid
        return {"valid": True, "error": None}


def _fmt_num(value: float) -> str:
    """Render numbers like JS does: 0.5 → '0.5', 30 → '30', 30.0 → '30'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class InputModeManager:
    """State machine NORMAL ↔ INPUT with decision-based side effects.

    Decisions returned to the caller (the controller executes them):
      ("none",)                 nothing to do
      ("render",)               scratchpad changed, re-render line 14
      ("full",)                 scratchpad full — show SCRATCHPAD VOLL once
      ("cleared",)              scratchpad cleared/restored, re-render
      ("home",)                 double-CLR emergency exit to home page
      ("parent",)               navigate to parent page
      ("toggle", source)        toggle a boolean entity
      ("write", source, value)  write value to entity (validated)
      ("error", message)        show scratchpad error (already applied)
      ("action", button)        execute a button config (navigation/datapoint)
    """

    def __init__(self, scratchpad: Scratchpad) -> None:
        self.scratchpad = scratchpad
        self.mode = "normal"
        self.last_clr_press = 0.0

    # -- keypad --------------------------------------------------------

    def handle_key_input(self, char: str) -> tuple:
        if self.mode == "normal":
            self.mode = "input"
            self.scratchpad.append(char)
            return ("render",)

        if not self.scratchpad.append(char):
            if not self.scratchpad.full_error_showing:
                self.scratchpad.full_error_showing = True
                return ("full",)
            return ("none",)
        return ("render",)

    def handle_plusminus(self) -> tuple:
        """Airbus convention: empty → '-', '-x' → 'x', 'x' → '-x'."""
        content = self.scratchpad.get_content()
        if not content:
            return self.handle_key_input("-")
        if content.startswith("-"):
            self.scratchpad.content = content[1:]
        else:
            if len(content) >= self.scratchpad.max_length:
                return ("none",)
            self.scratchpad.content = "-" + content
        return ("render",)

    # -- CLR -----------------------------------------------------------

    def handle_clr(self, now: float, has_parent: bool) -> tuple:
        """CLR priorities: double-CLR → home; clear/restore scratchpad;
        navigate to parent."""
        if self.last_clr_press > 0 and now - self.last_clr_press < DOUBLE_CLR_WINDOW:
            self.last_clr_press = 0.0
            self.scratchpad.clear()
            self.mode = "normal"
            return ("home",)

        if self.scratchpad.has_content() or self.scratchpad.error_showing:
            self.last_clr_press = now
            self.scratchpad.clear()
            if not self.scratchpad.has_content():
                self.mode = "normal"
            return ("cleared",)

        if has_parent:
            self.last_clr_press = now
            return ("parent",)

        self.last_clr_press = now
        return ("none",)

    # -- LSK -----------------------------------------------------------

    def handle_lsk(self, line: dict | None, side: str, meta_resolver) -> tuple:
        """LSK on a page line. ``meta_resolver(source)`` returns metadata
        {write, type, min, max, options} or None.

        Priority 1: datapoint display → metadata-driven toggle/write
        Priority 2: actionable button → execute action
        """
        if not line:
            return ("none",)
        side_config = line.get(side) or {}
        display = side_config.get("display") or {}
        button = side_config.get("button") or {}

        if display.get("type") == "datapoint" and display.get("source"):
            return self._handle_datapoint_lsk(display["source"], meta_resolver)

        if self.is_actionable_button(button):
            return ("action", button)

        return ("none",)

    def _handle_datapoint_lsk(self, source: str, meta_resolver) -> tuple:
        meta = meta_resolver(source)
        if not meta:
            return ("none",)

        if not meta.get("write"):
            self.scratchpad.show_error("SCHREIBGESCHUETZT")
            return ("error", "SCHREIBGESCHUETZT")

        meta_type = meta.get("type")

        if meta_type == "boolean":
            return ("toggle", source)

        if meta_type == "number":
            if not self.scratchpad.has_content():
                return ("none",)
            content = self.scratchpad.get_content()
            if not self.scratchpad.validate_numeric_format(content)["valid"] or content == "-":
                self.scratchpad.show_error("FORMAT ERROR")
                return ("error", "FORMAT ERROR")
            num = float(content)
            if (minimum := meta.get("min")) is not None and num < minimum:
                self.scratchpad.show_error("ENTRY OUT OF RANGE")
                return ("error", "ENTRY OUT OF RANGE")
            if (maximum := meta.get("max")) is not None and num > maximum:
                self.scratchpad.show_error("ENTRY OUT OF RANGE")
                return ("error", "ENTRY OUT OF RANGE")
            self.scratchpad.clear()
            self.mode = "normal"
            return ("write", source, num)

        if meta_type == "string":
            if not self.scratchpad.has_content():
                return ("none",)
            content = self.scratchpad.get_content()
            options = meta.get("options")
            if isinstance(options, list) and content not in options:
                self.scratchpad.show_error("UNGUELTIGE AUSWAHL")
                return ("error", "UNGUELTIGE AUSWAHL")
            self.scratchpad.clear()
            self.mode = "normal"
            return ("write", source, content)

        return ("none",)

    @staticmethod
    def is_actionable_button(button: dict | None) -> bool:
        """The admin UI saves button.type='datapoint'/'navigation' with an
        empty target; such buttons are not actionable."""
        if not button or button.get("type") == "empty" or not button.get("type"):
            return False
        if button.get("type") in ("navigation", "datapoint"):
            return bool(button.get("target"))
        return True

    # -- state ---------------------------------------------------------

    def get_mode(self) -> str:
        return self.mode

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def get_state(self) -> dict:
        return {
            "mode": self.mode,
            "scratchpad_content": self.scratchpad.get_content(),
            "scratchpad_valid": self.scratchpad.get_valid(),
        }
