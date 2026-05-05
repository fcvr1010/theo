"""Unit tests for :mod:`theo._embed` helpers that don't require fastembed."""

from __future__ import annotations

from theo._embed import make_edge_text, make_node_text


class TestMakeNodeText:
    def test_joins_description_and_notes(self) -> None:
        assert make_node_text("desc", "notes body") == "desc\n\nnotes body"

    def test_drops_none_description(self) -> None:
        assert make_node_text(None, "notes only") == "notes only"

    def test_drops_none_notes(self) -> None:
        assert make_node_text("desc only", None) == "desc only"

    def test_both_none_returns_blank(self) -> None:
        assert make_node_text(None, None) == ""

    def test_empty_strings_treated_as_missing(self) -> None:
        assert make_node_text("", "") == ""


class TestMakeEdgeText:
    def test_returns_description(self) -> None:
        assert make_edge_text("belongs to") == "belongs to"

    def test_none_returns_blank(self) -> None:
        assert make_edge_text(None) == ""

    def test_empty_returns_blank(self) -> None:
        assert make_edge_text("") == ""
