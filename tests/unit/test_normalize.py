"""Tests for shared normalization utilities."""

import pytest

from hailmary.ingestion.normalize import content_hash, strip_html


@pytest.mark.unit
def test_content_hash_is_deterministic():
    assert content_hash("KC passing stats") == content_hash("KC passing stats")


@pytest.mark.unit
def test_content_hash_differs_for_different_text():
    assert content_hash("KC passing stats") != content_hash("LV passing stats")


@pytest.mark.unit
def test_strip_html_removes_tags_and_collapses_whitespace():
    raw = "<p>Mahomes  <b>threw</b> for\n300 yards.</p>"
    assert strip_html(raw) == "Mahomes threw for 300 yards."


@pytest.mark.unit
def test_strip_html_handles_plain_text_unchanged_besides_whitespace():
    assert strip_html("already   plain text") == "already plain text"
