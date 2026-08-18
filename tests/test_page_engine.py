"""Port of ioBroker.mcdu test/unit/pageRenderer.test.js and navigation.test.js.

These tests are the porting specification: they mirror the mocha suite of the
reference implementation to guarantee behavior parity of the Python engine.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "mcdu"))

from page_engine import (  # noqa: E402
    PageEngine,
    align_text,
    evaluate_condition,
    pad_or_truncate,
    sanitize_ascii,
)


def _label_line(row, text, col_data=None, label="", right=None):
    display = {"type": "label", "text": text}
    if col_data:
        display["colData"] = col_data
    return {
        "row": row,
        "left": {"label": label, "display": display, "button": {"type": "empty"}},
        "right": right
        or {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
    }


@pytest.fixture
def pages():
    return [
        {
            "id": "home-main",
            "name": "Home",
            "lines": [
                _label_line(3, "WELCOME", "white"),
                _label_line(5, "21.5 C", "white", label="TEMPERATUR"),
                _label_line(7, "LIGHTS", "white"),
            ],
        },
        {
            "id": "long-page",
            "name": "Long List",
            "lines": [_label_line(100 + i, f"ITEM {i}") for i in range(1, 10)],
        },
        {
            "id": "sub-labels-page",
            "name": "Sub Labels",
            "lines": [
                _label_line(3, "TITLE"),
                _label_line(5, "21.5 C", label="WOHNZIMMER"),
                _label_line(7, "19.0 C", label="KUECHE"),
                _label_line(9, "NO SUB"),
            ],
        },
        {
            "id": "left-right-page",
            "name": "Left Right",
            "lines": [
                {
                    "row": 3,
                    "left": {
                        "label": "LINKS",
                        "display": {"type": "label", "text": "Decke", "colData": "white"},
                        "button": {"type": "empty"},
                    },
                    "right": {
                        "label": "RECHTS",
                        "display": {"type": "label", "text": "AN", "colData": "green"},
                        "button": {"type": "empty"},
                    },
                },
                _label_line(5, "Only Left", "white"),
                {
                    "row": 7,
                    "left": {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
                    "right": {
                        "label": "",
                        "display": {"type": "label", "text": "Only Right", "colData": "amber"},
                        "button": {"type": "empty"},
                    },
                },
            ],
        },
    ]


@pytest.fixture
def engine(pages):
    return PageEngine(pages)


# ---------------------------------------------------------------------------
# Even Row Sub-Labels
# ---------------------------------------------------------------------------


class TestSubLabels:
    def test_sub_labels_on_even_rows(self, engine):
        lines = engine.render_page("sub-labels-page")
        assert "WOHNZIMMER" in lines[3]["text"]
        assert lines[3]["color"] == "white"
        assert "KUECHE" in lines[5]["text"]
        assert lines[5]["color"] == "white"

    def test_blank_even_rows_without_sub_label(self, engine):
        lines = engine.render_page("sub-labels-page")
        assert lines[7]["text"].strip() == ""
        assert lines[7]["color"] == "white"

    def test_even_rows_default_color(self, engine):
        lines = engine.render_page("home-main")
        for idx in [1, 3, 5, 7, 9, 11]:
            assert lines[idx]["color"] == "white"

    def test_left_and_right_sub_labels(self, engine):
        lines = engine.render_page("left-right-page")
        assert "LINKS" in lines[1]["text"]
        assert "RECHTS" in lines[1]["text"]
        assert "Decke" in lines[2]["text"]
        assert "AN" in lines[2]["text"]


# ---------------------------------------------------------------------------
# Left/Right Column Rendering
# ---------------------------------------------------------------------------


class TestLeftRight:
    def test_compose_left_right_24_chars(self, engine):
        lines = engine.render_page("left-right-page")
        row3 = lines[2]
        assert len(row3["text"]) == 24
        assert "Decke" in row3["text"][:12]
        assert "AN" in row3["text"][12:]

    def test_segments_when_colors_differ(self, engine):
        lines = engine.render_page("left-right-page")
        row3 = lines[2]
        assert isinstance(row3.get("segments"), list) and len(row3["segments"]) == 2
        assert row3["segments"][0]["color"] == "white"
        assert row3["segments"][1]["color"] == "green"
        assert "Decke" in row3["segments"][0]["text"]
        assert "AN" in row3["segments"][1]["text"]

    def test_no_segments_single_side(self, engine):
        lines = engine.render_page("left-right-page")
        assert "segments" not in lines[4]
        assert "segments" not in lines[6]

    def test_no_segments_same_color(self, pages):
        pages.append(
            {
                "id": "same-color-page",
                "name": "Same Color",
                "lines": [
                    {
                        "row": 3,
                        "left": {
                            "label": "",
                            "display": {"type": "label", "text": "LEFT", "colData": "green"},
                            "button": {"type": "empty"},
                        },
                        "right": {
                            "label": "",
                            "display": {"type": "label", "text": "RIGHT", "colData": "green"},
                            "button": {"type": "empty"},
                        },
                    }
                ],
            }
        )
        engine = PageEngine(pages)
        lines = engine.render_page("same-color-page")
        assert "segments" not in lines[2]
        assert lines[2]["color"] == "green"

    def test_full_width_left_only(self, engine):
        lines = engine.render_page("left-right-page")
        assert "Only Left" in lines[4]["text"]
        assert len(lines[4]["text"]) == 24

    def test_right_aligned_right_only(self, engine):
        lines = engine.render_page("left-right-page")
        assert "Only Right" in lines[6]["text"]
        assert lines[6]["text"].lstrip() == "Only Right"


# ---------------------------------------------------------------------------
# Status Bar (Row 1)
# ---------------------------------------------------------------------------


class TestStatusBar:
    def test_status_bar_row_1(self, engine):
        lines = engine.render_page("home-main")
        assert lines[0]["color"] == "white"
        assert "HOME" in lines[0]["text"]

    def test_time_in_status_bar(self, engine):
        lines = engine.render_page("home-main")
        assert re.search(r"\d{2}:\d{2}", lines[0]["text"])

    def test_page_indicator_when_paginated(self, engine):
        lines = engine.render_page("long-page")
        assert "1/2" in lines[0]["text"]

    def test_no_page_indicator_single_page(self, engine):
        lines = engine.render_page("home-main")
        assert not re.search(r"\d+/\d+", lines[0]["text"])

    def test_status_bar_24_chars(self, engine):
        lines = engine.render_page("home-main")
        assert len(lines[0]["text"]) == 24

    def test_page_name_uppercase(self, engine):
        result = engine._render_status_bar("home-main")
        assert "HOME" in result["text"]
        assert result["color"] == "white"

    def test_fallback_to_page_id(self, pages):
        pages.append({"id": "no-name-page", "lines": []})
        engine = PageEngine(pages)
        result = engine._render_status_bar("no-name-page")
        assert "NO-NAME-PAGE" in result["text"]

    def test_truncate_long_page_names(self, pages):
        pages.append({"id": "x", "name": "A Very Long Page Name That Exceeds", "lines": []})
        engine = PageEngine(pages)
        result = engine._render_status_bar("x")
        assert len(result["text"]) == 24


class TestBreadcrumbStatusBar:
    def test_breadcrumb_chain(self, engine):
        engine.breadcrumb = [
            {"id": "home-main", "name": "Home"},
            {"id": "klima-main", "name": "Klima"},
        ]
        result = engine._render_status_bar("klima-main")
        assert "HOME > KLIMA" in result["text"]
        assert result["color"] == "white"

    def test_root_page_name_only(self, engine):
        engine.breadcrumb = [{"id": "home-main", "name": "Home"}]
        result = engine._render_status_bar("home-main")
        assert "HOME" in result["text"]

    def test_truncate_long_breadcrumbs(self, engine):
        engine.breadcrumb = [
            {"id": "home", "name": "Hauptmenue"},
            {"id": "beleuchtung", "name": "Beleuchtung"},
            {"id": "wohnzimmer", "name": "Wohnzimmer"},
        ]
        result = engine._render_status_bar("wohnzimmer")
        assert len(result["text"]) == 24

    def test_fallback_without_breadcrumb(self, engine):
        engine.breadcrumb = []
        result = engine._render_status_bar("home-main")
        assert "HOME" in result["text"]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_paginate_over_6_items(self, engine):
        engine.render_page("long-page")
        assert engine.total_pages == 2
        assert engine.current_page_offset == 0

    def test_no_pagination_up_to_6_items(self, engine):
        engine.render_page("home-main")
        assert engine.total_pages == 1
        assert engine.current_page_offset == 0

    def test_first_6_items_on_page_1(self, engine):
        lines = engine.render_page("long-page")
        assert "ITEM 1" in lines[2]["text"]
        assert "ITEM 6" in lines[12]["text"]

    def test_remaining_items_on_page_2(self, engine):
        engine.current_page_offset = 1
        lines = engine.render_page("long-page")
        assert "ITEM 7" in lines[2]["text"]
        assert "ITEM 8" in lines[4]["text"]
        assert "ITEM 9" in lines[6]["text"]

    def test_clamp_offset(self, engine):
        engine.current_page_offset = 99
        engine.render_page("long-page")
        assert engine.current_page_offset == 1

    def test_reset_for_non_paginated(self, engine):
        engine.current_page_offset = 5
        engine.total_pages = 10
        engine.render_page("home-main")
        assert engine.total_pages == 1
        assert engine.current_page_offset == 0

    def test_scroll_indicators(self, pages):
        engine = PageEngine(pages)
        lines = engine.render_page("long-page")
        assert "^" not in lines[1]["text"]
        assert "v" in lines[11]["text"]

        engine.current_page_offset = 1
        lines = engine.render_page("long-page")
        assert "^" in lines[1]["text"]
        assert "v" not in lines[11]["text"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_pad_short(self):
        assert pad_or_truncate("abc", 6) == "abc   "

    def test_truncate_long(self):
        assert pad_or_truncate("abcdef", 3) == "abc"

    def test_exact_unchanged(self):
        assert pad_or_truncate("abc", 3) == "abc"

    def test_align_left(self):
        assert align_text("hi", "left", 10) == "hi        "

    def test_align_right(self):
        assert align_text("hi", "right", 10) == "        hi"

    def test_align_center(self):
        assert align_text("hi", "center", 10) == "    hi    "

    def test_sanitize_ascii(self):
        assert sanitize_ascii("Küche") == "Kuche"
        assert sanitize_ascii("GRÖSSE") == "GROSSE"
        assert sanitize_ascii("straße") == "strasse"
        assert sanitize_ascii("smiley☺") == "smiley?"
        assert sanitize_ascii("21.5°") == "21.5°"

    def test_evaluate_condition(self):
        assert evaluate_condition(25, "> 20") is True
        assert evaluate_condition(15, "> 20") is False
        assert evaluate_condition(20, ">= 20") is True
        assert evaluate_condition("on", "== on") is True
        assert evaluate_condition("off", "!= on") is True
        assert evaluate_condition(25, "> 20 && < 30") is True
        assert evaluate_condition(35, "> 20 && < 30") is False
        assert evaluate_condition(5, "< 10 || > 90") is True


# ---------------------------------------------------------------------------
# Line Rendering & Output
# ---------------------------------------------------------------------------


class TestLineRendering:
    def test_navigation_lines_without_angle_indicators(self):
        pages = [
            {
                "id": "test-nav",
                "name": "Test Nav",
                "lines": [
                    {
                        "row": 3,
                        "left": {
                            "label": "",
                            "display": {"type": "label", "text": "LIGHTS"},
                            "button": {"type": "navigation", "action": "goto", "target": "lights"},
                        },
                        "right": {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
                    }
                ],
            }
        ]
        engine = PageEngine(pages)
        engine.breadcrumb = [{"id": "test-nav", "name": "Test Nav"}]
        lines = engine.render_page("test-nav")
        assert not lines[2]["text"].startswith("<")
        assert not lines[2]["text"].endswith(">")
        assert lines[2]["text"].strip() == "LIGHTS"

    def test_exactly_14_lines(self, engine):
        assert len(engine.render_page("home-main")) == 14

    def test_all_lines_24_chars(self, engine):
        for line in engine.render_page("home-main"):
            assert len(line["text"]) == 24

    def test_error_page_for_unknown_id(self, engine):
        lines = engine.render_page("nonexistent")
        assert any(
            "NICHT GEFUNDEN" in l["text"] and l["color"] == "red" for l in lines
        )

    def test_empty_page_message(self, pages):
        pages.append({"id": "empty-page", "name": "Empty", "lines": []})
        engine = PageEngine(pages)
        lines = engine.render_page("empty-page")
        assert any("KEINE INHALTE" in l["text"] and l["color"] == "amber" for l in lines)

    def test_scratchpad_placeholder_row_14(self, engine):
        lines = engine.render_page("home-main")
        assert lines[13]["text"].startswith("____________________")


# ---------------------------------------------------------------------------
# Datapoint Rendering (value resolver)
# ---------------------------------------------------------------------------


def _datapoint_page(display_extra=None):
    display = {
        "type": "datapoint",
        "text": "TEMP",
        "source": "sensor.temp",
        "colData": "green",
    }
    if display_extra:
        display.update(display_extra)
    return [
        {
            "id": "dp",
            "name": "DP",
            "lines": [
                {
                    "row": 3,
                    "left": {"label": "", "display": display, "button": {"type": "empty"}},
                    "right": {"label": "", "display": {"type": "empty"}, "button": {"type": "empty"}},
                }
            ],
        }
    ]


class TestDatapoints:
    def test_value_with_format_and_unit(self):
        engine = PageEngine(
            _datapoint_page({"format": "%.1f", "unit": "C"}),
            value_resolver=lambda s: {"value": 21.53, "available": True},
        )
        lines = engine.render_page("dp")
        assert "TEMP 21.5 C" in lines[2]["text"]
        assert lines[2]["color"] == "green"

    def test_missing_source_shows_dashes_amber(self):
        engine = PageEngine(_datapoint_page(), value_resolver=lambda s: None)
        lines = engine.render_page("dp")
        assert "TEMP ---" in lines[2]["text"]
        assert lines[2]["color"] == "amber"

    def test_unavailable_shows_offline_amber(self):
        engine = PageEngine(
            _datapoint_page(),
            value_resolver=lambda s: {"value": None, "available": False},
        )
        lines = engine.render_page("dp")
        assert "TEMP OFFLINE" in lines[2]["text"]
        assert lines[2]["color"] == "amber"

    def test_none_value_shows_dashes(self):
        engine = PageEngine(
            _datapoint_page(),
            value_resolver=lambda s: {"value": None, "available": True},
        )
        lines = engine.render_page("dp")
        assert "TEMP ---" in lines[2]["text"]

    def test_color_rules_override(self):
        engine = PageEngine(
            _datapoint_page(
                {"colorRules": [{"condition": "> 25", "color": "red"}]}
            ),
            value_resolver=lambda s: {"value": 30, "available": True},
        )
        lines = engine.render_page("dp")
        assert lines[2]["color"] == "red"


# ---------------------------------------------------------------------------
# Navigation (port of navigation.test.js)
# ---------------------------------------------------------------------------


NAV_PAGES = [
    {"id": "home-main", "name": "Home", "parent": None},
    {"id": "lights-main", "name": "Lights", "parent": "home-main"},
    {"id": "klima-main", "name": "Klima", "parent": "home-main"},
    {"id": "security-main", "name": "Security", "parent": "home-main"},
    {"id": "klima-wohn", "name": "Wohnzimmer", "parent": "klima-main"},
]


class TestBreadcrumb:
    def _engine(self, pages=None):
        return PageEngine(
            pages
            or [
                {"id": "home-main", "name": "Home", "parent": None},
                {"id": "klima-main", "name": "Klima", "parent": "home-main"},
                {"id": "klima-wohn", "name": "Wohnzimmer", "parent": "klima-main"},
            ]
        )

    def test_full_path_nested(self):
        result = self._engine().build_breadcrumb("klima-wohn")
        assert [b["id"] for b in result] == ["home-main", "klima-main", "klima-wohn"]

    def test_single_entry_root(self):
        result = self._engine().build_breadcrumb("home-main")
        assert [b["id"] for b in result] == ["home-main"]

    def test_nonexistent_page(self):
        assert self._engine().build_breadcrumb("does-not-exist") == []

    def test_circular_parents_no_hang(self):
        engine = self._engine(
            [
                {"id": "a", "name": "A", "parent": "b"},
                {"id": "b", "name": "B", "parent": "a"},
            ]
        )
        assert len(engine.build_breadcrumb("a")) < 10


class TestSlewNavigation:
    def _engine(self):
        return PageEngine(list(NAV_PAGES))

    def test_next_sibling(self):
        assert self._engine().navigate_next("lights-main") == "klima-main"

    def test_wrap_last_to_first(self):
        assert self._engine().navigate_next("security-main") == "lights-main"

    def test_previous_sibling(self):
        assert self._engine().navigate_previous("klima-main") == "lights-main"

    def test_wrap_first_to_last(self):
        assert self._engine().navigate_previous("lights-main") == "security-main"

    def test_stay_without_siblings(self):
        assert self._engine().navigate_next("klima-wohn") == "klima-wohn"

    def test_stay_on_only_root(self):
        assert self._engine().navigate_next("home-main") == "home-main"


class TestParentNavigation:
    def test_parent(self):
        engine = PageEngine(list(NAV_PAGES))
        assert engine.parent_of("klima-main") == "home-main"

    def test_root_has_no_parent(self):
        engine = PageEngine(list(NAV_PAGES))
        assert engine.parent_of("home-main") is None
