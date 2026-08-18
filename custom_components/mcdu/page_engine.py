"""Pure-Python page engine for the MCDU display.

Port of the reference implementation in ioBroker.mcdu (lib/rendering/PageRenderer.js
and lib/utils/lineNormalizer.js). Behavior is specified by the mocha test suite of
that repository, mirrored here in tests/test_page_engine.py.

This module is deliberately free of Home Assistant imports so it can be unit-tested
standalone. Integration glue (entity resolution, MQTT publishing) lives in
controller.py.

Page format (one current format, no legacy migrations):
    page: { id, name, parent?, pageNameColor?, lines: [line] }
    line: { row, left: side, right: side }
    side: { label, display: { type, text, colLabel, colData, source?, format?,
            unit?, align?, colorRules? }, button: { type, action?, target? } }
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

COLUMNS = 24
ROWS = 14
HALF_WIDTH = COLUMNS // 2
ODD_ROWS = [3, 5, 7, 9, 11, 13]
ITEMS_PER_PAGE = 6

EMPTY_SIDE = {
    "label": "",
    "display": {"type": "empty"},
    "button": {"type": "empty"},
}

_ASCII_MAP = str.maketrans(
    {
        **{c: "a" for c in "äàáâãå"},
        **{c: "A" for c in "ÄÀÁÂÃÅ"},
        **{c: "e" for c in "éèêë"},
        **{c: "E" for c in "ÉÈÊË"},
        **{c: "i" for c in "íìîï"},
        **{c: "I" for c in "ÍÌÎÏ"},
        **{c: "o" for c in "öóòôõ"},
        **{c: "O" for c in "ÖÓÒÔÕ"},
        **{c: "u" for c in "üúùû"},
        **{c: "U" for c in "ÜÚÙÛ"},
        "ß": "ss",
    }
)

# Characters the hardware font can render besides printable ASCII
_ALLOWED_EXTRA = "°Δ←↑→↓▶◀□◇"
_DISALLOWED = re.compile(f"[^\x20-\x7e{_ALLOWED_EXTRA}]")


def sanitize_ascii(text: str) -> str:
    """Transliterate umlauts/accents and replace unrenderable chars with '?'."""
    return _DISALLOWED.sub("?", text.translate(_ASCII_MAP))


def pad_or_truncate(text: str, length: int) -> str:
    if len(text) > length:
        return text[:length]
    return text.ljust(length)


def align_text(text: str, align: str, width: int) -> str:
    text = text.strip()
    if len(text) >= width:
        return text[:width]
    padding = width - len(text)
    if align == "center":
        left_pad = padding // 2
        return " " * left_pad + text + " " * (padding - left_pad)
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def normalize_line(line: dict | None) -> dict | None:
    """Ensure a line config has the expected left/right structure."""
    if not line:
        return None
    return {
        "row": line.get("row"),
        "left": {**EMPTY_SIDE, **(line.get("left") or {})},
        "right": {**EMPTY_SIDE, **(line.get("right") or {})},
    }


def get_display_text(display: dict | None) -> str:
    if not display:
        return ""
    return display.get("text") or display.get("label") or ""


def effective_display_type(display: dict | None) -> str:
    """Coerce type 'empty' to 'label' when text is present (admin UI quirk)."""
    if not display:
        return "empty"
    dtype = display.get("type")
    if dtype and dtype != "empty":
        return dtype
    if display.get("text") or display.get("label"):
        return "label"
    return "empty"


def line_has_display(line: dict | None) -> bool:
    if not line:
        return False
    left = effective_display_type((line.get("left") or {}).get("display"))
    right = effective_display_type((line.get("right") or {}).get("display"))
    return left != "empty" or right != "empty"


def _sprintf(fmt: str, value: Any) -> str:
    """Best-effort port of sprintf-style formatting ('%.1f', '%d', '%s')."""
    if any(spec in fmt for spec in ("d", "i", "u", "x", "X", "o")) and not isinstance(
        value, int
    ):
        value = int(float(value))
    elif any(spec in fmt for spec in ("f", "e", "g")) and not isinstance(value, float):
        value = float(value)
    return fmt % value


_NUM_COND = re.compile(r"^\s*(<=|>=|==|===|!=|!==|<|>)\s*(-?\d+\.?\d*)\s*$")
_STR_COND = re.compile(r"^\s*(==|===|!=|!==)\s*[\"']?([^\"'\s]+)[\"']?\s*$")

_NUM_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "===": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "!==": lambda a, b: a != b,
}


def _evaluate_simple_condition(value: Any, condition: str) -> bool:
    try:
        num_value = float(value)
        is_numeric = True
    except (TypeError, ValueError):
        is_numeric = False

    if is_numeric:
        match = _NUM_COND.match(condition)
        if match:
            op, compare = match.groups()
            return _NUM_OPS[op](num_value, float(compare))
    match = _STR_COND.match(condition)
    if match:
        op, compare = match.groups()
        equal = str(value) == compare
        return equal if op in ("==", "===") else not equal
    return False


def evaluate_condition(value: Any, condition: str) -> bool:
    """Evaluate a color-rule condition like '> 20', '== on', '> 5 && < 30'."""
    for or_part in condition.split("||"):
        if all(
            _evaluate_simple_condition(value, and_part)
            for and_part in or_part.split("&&")
        ):
            return True
    return False


def evaluate_color_rules(value: Any, color_rules: list[dict]) -> str | None:
    for rule in color_rules:
        condition = rule.get("condition")
        if condition and _safe_evaluate(value, condition):
            return rule.get("color")
    return None


def _safe_evaluate(value: Any, condition: str) -> bool:
    try:
        return evaluate_condition(value, condition)
    except Exception:  # noqa: BLE001 — a broken rule must never break rendering
        return False


class PageEngine:
    """Renders page configs to 14x24 display lines and handles navigation.

    ``value_resolver(source)`` returns ``{"value": Any, "available": bool}`` or
    ``None`` when the source does not exist. ``scratchpad_provider()`` returns
    ``(text, color)`` for row 14. ``clock()`` returns a datetime for the status
    bar. All three are injectable for testing.
    """

    def __init__(
        self,
        pages: list[dict],
        default_color: str = "white",
        value_resolver: Callable[[str], dict | None] | None = None,
        scratchpad_provider: Callable[[], tuple[str, str]] | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.pages = pages
        self.default_color = default_color
        self.value_resolver = value_resolver
        self.scratchpad_provider = scratchpad_provider
        self.clock = clock

        self.breadcrumb: list[dict] = []
        self.current_page_offset = 0
        self.total_pages = 1
        # row -> normalized line of the last rendered (possibly paginated) view
        self._last_row_map: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Page lookup & navigation
    # ------------------------------------------------------------------

    def find_page(self, page_id: str) -> dict | None:
        return next((p for p in self.pages if p.get("id") == page_id), None)

    def build_breadcrumb(self, page_id: str) -> list[dict]:
        """Walk the parent chain, root first. Cycle-safe."""
        breadcrumb: list[dict] = []
        current_id: str | None = page_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            page = self.find_page(current_id)
            if not page:
                break
            breadcrumb.insert(0, {"id": page["id"], "name": page.get("name") or page["id"]})
            current_id = page.get("parent") or None
        return breadcrumb

    def parent_of(self, page_id: str) -> str | None:
        page = self.find_page(page_id)
        return (page.get("parent") or None) if page else None

    def get_siblings(self, page_id: str) -> list[dict]:
        page = self.find_page(page_id)
        if not page:
            return []
        parent_id = page.get("parent") or None
        return [p for p in self.pages if (p.get("parent") or None) == parent_id]

    def navigate_next(self, page_id: str) -> str:
        return self._navigate_sibling(page_id, 1)

    def navigate_previous(self, page_id: str) -> str:
        return self._navigate_sibling(page_id, -1)

    def _navigate_sibling(self, page_id: str, step: int) -> str:
        siblings = self.get_siblings(page_id)
        if len(siblings) <= 1:
            return page_id
        index = next((i for i, p in enumerate(siblings) if p["id"] == page_id), 0)
        return siblings[(index + step) % len(siblings)]["id"]

    def line_at_row(self, row: int) -> dict | None:
        """Line shown at a display row in the last render (pagination-aware)."""
        return self._last_row_map.get(row)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_page(self, page_id: str) -> list[dict]:
        """Render a page to 14 line dicts {text, color[, segments]}."""
        try:
            page = self.find_page(page_id)
            if not page:
                return self._message_page("SEITE NICHT GEFUNDEN", "red")

            raw_lines = page.get("lines") or []
            if not raw_lines:
                return self._message_page("KEINE INHALTE", "amber")

            normalized = [normalize_line(l) for l in raw_lines]

            # Pagination: collect items with display content on either side
            all_items = [l for l in normalized if line_has_display(l)]
            if len(all_items) > ITEMS_PER_PAGE:
                self.total_pages = -(-len(all_items) // ITEMS_PER_PAGE)
                self.current_page_offset = min(
                    self.current_page_offset, self.total_pages - 1
                )
            else:
                self.total_pages = 1
                self.current_page_offset = 0

            paginated_map: dict[int, dict] = {}
            if self.total_pages > 1:
                start = self.current_page_offset * ITEMS_PER_PAGE
                for i, item in enumerate(all_items[start : start + ITEMS_PER_PAGE]):
                    paginated_map[ODD_ROWS[i]] = item

            def line_for_row(row: int) -> dict | None:
                if self.total_pages > 1:
                    return paginated_map.get(row)
                return next((l for l in normalized if l["row"] == row), None)

            self._last_row_map = {row: l for row in ODD_ROWS if (l := line_for_row(row))}

            lines: list[dict] = []
            for row in range(1, ROWS + 1):
                try:
                    if row % 2 == 0 and 2 <= row <= 12:
                        lines.append(self._render_sub_label(line_for_row(row + 1)))
                    elif row == 1:
                        lines.append(self._render_status_bar(page_id))
                    else:
                        lines.append(self._render_line(line_for_row(row), row))
                except Exception:  # noqa: BLE001 — one bad line must not kill the page
                    lines.append(
                        {"text": pad_or_truncate("-- FEHLER --", COLUMNS), "color": "red"}
                    )

            # Scroll indicators when paginated (indices 1 and 11 = rows 2 and 12)
            if self.total_pages > 1:
                if self.current_page_offset > 0:
                    lines[1] = {
                        "text": pad_or_truncate(" " * 22 + "^", COLUMNS),
                        "color": "cyan",
                    }
                if self.current_page_offset < self.total_pages - 1:
                    lines[11] = {
                        "text": pad_or_truncate(" " * 22 + "v", COLUMNS),
                        "color": "cyan",
                    }

            return lines
        except Exception:  # noqa: BLE001
            return self._message_page("RENDERFEHLER", "red")

    def _message_page(self, message: str, color: str) -> list[dict]:
        blank = {"text": pad_or_truncate("", COLUMNS), "color": "white"}
        lines = [dict(blank) for _ in range(6)]
        lines.append({"text": pad_or_truncate(f"    {message}", COLUMNS), "color": color})
        lines.extend(dict(blank) for _ in range(7))
        return lines

    def _render_sub_label(self, line: dict | None) -> dict:
        left = (line or {}).get("left") or {}
        right = (line or {}).get("right") or {}
        left_label = left.get("label") or ""
        right_label = right.get("label") or ""
        left_color = (left.get("display") or {}).get("colLabel") or self.default_color
        right_color = (right.get("display") or {}).get("colLabel") or self.default_color

        if left_label and right_label:
            gap = COLUMNS - len(left_label) - len(right_label)
            text = left_label + " " * max(0, gap) + right_label
        elif left_label:
            text = left_label
        elif right_label:
            text = " " * (COLUMNS - len(right_label)) + right_label
        else:
            text = ""

        result = {"text": pad_or_truncate(text, COLUMNS), "color": left_color}

        if left_label and right_label and left_color != right_color:
            result["segments"] = [
                {"text": left_label.ljust(HALF_WIDTH), "color": left_color},
                {"text": right_label.rjust(HALF_WIDTH), "color": right_color},
            ]
        return result

    def _render_status_bar(self, page_id: str) -> dict:
        breadcrumb = self.breadcrumb or []
        if len(breadcrumb) > 1:
            breadcrumb_text = " > ".join(
                sanitize_ascii(b["name"].upper()) for b in breadcrumb
            )
        else:
            page = self.find_page(page_id)
            breadcrumb_text = sanitize_ascii(
                ((page or {}).get("name") or page_id).upper()
            )

        now = self.clock()
        time_text = f"{now.hour:02d}:{now.minute:02d}"

        page_indicator = (
            f" {self.current_page_offset + 1}/{self.total_pages}"
            if self.total_pages > 1
            else ""
        )
        right_part = f"{page_indicator} {time_text}"
        max_name_len = COLUMNS - len(right_part)

        if len(breadcrumb_text) > max_name_len and len(breadcrumb) > 2:
            # Shorten intermediate segments to their first 4 chars
            parts = []
            for i, b in enumerate(breadcrumb):
                name = sanitize_ascii(b["name"].upper())
                if 0 < i < len(breadcrumb) - 1 and len(name) > 4:
                    name = name[:4]
                parts.append(name)
            breadcrumb_text = " > ".join(parts)

        truncated = breadcrumb_text[:max_name_len]
        padding = max(0, COLUMNS - len(truncated) - len(right_part))
        status_text = truncated + " " * padding + right_part

        page = self.find_page(page_id)
        name_color = (page or {}).get("pageNameColor") or self.default_color
        time_color = self.default_color

        result = {"text": pad_or_truncate(status_text, COLUMNS), "color": name_color}

        if name_color != time_color:
            split = len(truncated) + padding
            result["segments"] = [
                {"text": status_text[:split], "color": name_color},
                {"text": status_text[split:], "color": time_color},
            ]
        return result

    def _render_line(self, line: dict | None, row: int) -> dict:
        if row == ROWS:
            if self.scratchpad_provider:
                text, color = self.scratchpad_provider()
                return {"text": pad_or_truncate(text, COLUMNS), "color": color}
            return {
                "text": pad_or_truncate("____________________", COLUMNS),
                "color": "white",
            }

        normalized = normalize_line(line)
        if not normalized or not line_has_display(normalized):
            return {"text": pad_or_truncate("", COLUMNS), "color": self.default_color}

        left_result = self._render_side(normalized["left"].get("display"))
        right_result = self._render_side(normalized["right"].get("display"))

        left_has = bool(left_result["text"].strip())
        right_has = bool(right_result["text"].strip())

        segments = None
        if left_has and right_has:
            left_text = left_result["text"][:HALF_WIDTH].ljust(HALF_WIDTH)
            right_text = right_result["text"][:HALF_WIDTH].rjust(HALF_WIDTH)
            text = left_text + right_text
            color = left_result["color"]
            if left_result["color"] != right_result["color"]:
                segments = [
                    {"text": left_text, "color": left_result["color"]},
                    {"text": right_text, "color": right_result["color"]},
                ]
        elif left_has:
            align = (normalized["left"].get("display") or {}).get("align") or "left"
            text = align_text(left_result["text"], align, COLUMNS)
            color = left_result["color"]
        elif right_has:
            align = (normalized["right"].get("display") or {}).get("align") or "right"
            text = align_text(right_result["text"], align, COLUMNS)
            color = right_result["color"]
        else:
            text = ""
            color = self.default_color

        result = {"text": pad_or_truncate(text, COLUMNS), "color": color}
        if segments:
            result["segments"] = segments
        return result

    def _render_side(self, display: dict | None) -> dict:
        dtype = effective_display_type(display)
        if dtype == "empty":
            return {"text": "", "color": self.default_color}

        if dtype == "label":
            return {
                "text": get_display_text(display),
                "color": display.get("colData") or self.default_color,
            }
        if dtype == "datapoint":
            return self._render_datapoint(display)
        return {"text": "", "color": self.default_color}

    def _render_datapoint(self, display: dict) -> dict:
        source = display.get("source")
        label = get_display_text(display)
        col_data = display.get("colData") or self.default_color

        if not source:
            return {"text": label or "", "color": col_data}

        resolved = self.value_resolver(source) if self.value_resolver else None
        prefix = f"{label} " if label else ""

        if resolved is None:
            return {"text": f"{prefix}---", "color": "amber"}
        if not resolved.get("available", True):
            return {"text": f"{prefix}OFFLINE", "color": "amber"}

        value = resolved.get("value")
        if value is None:
            formatted = "---"
        else:
            fmt = display.get("format")
            if fmt:
                try:
                    formatted = _sprintf(fmt, value)
                except (TypeError, ValueError):
                    formatted = str(value)
            else:
                formatted = str(value)
            if len(formatted) > COLUMNS - 5:
                formatted = formatted[: COLUMNS - 8] + "..."

        unit = display.get("unit")
        suffix = f" {unit}" if unit else ""
        content = f"{prefix}{formatted}{suffix}"
        if len(content) > COLUMNS:
            content = content[: COLUMNS - 3] + "..."

        color = col_data
        color_rules = display.get("colorRules")
        if isinstance(color_rules, list):
            rule_color = evaluate_color_rules(value, color_rules)
            if rule_color:
                color = rule_color
        return {"text": content, "color": color}
