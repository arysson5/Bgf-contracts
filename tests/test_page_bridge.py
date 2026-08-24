from app.utils.page_bridge import _JS, _parse_event
from app.utils.sync_scroll import sync_scroll_classes


def test_parse_event_accepts_json_string():
    event = _parse_event('{"type":"rc","kind":"docx","para":"34","ts":1}')
    assert event is not None
    assert event["type"] == "rc"
    assert event["kind"] == "docx"
    assert event["para"] == "34"


def test_parse_event_ignores_empty():
    assert _parse_event(None) is None
    assert _parse_event("") is None
    assert _parse_event({"foo": 1}) is None


def test_bridge_js_uses_v2_trigger_not_location():
    assert "setTriggerValue" in _JS
    assert "export default function" in _JS
    assert "parent.location" not in _JS
    assert "bgf-sbs-grid" in _JS
    assert "shiftKey" in _JS


def test_sync_scroll_classes_include_group():
    classes = sync_scroll_classes("cmp_sbs")
    assert "bgf-sync-scroll" in classes
    assert "bgf-sg-cmp_sbs" in classes
