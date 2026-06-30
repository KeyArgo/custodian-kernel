"""Tests for the EventBus."""
from custodian.bus import EventBus


def test_basic_emit_and_receive():
    bus = EventBus()
    received = []

    @bus.on("test_event")
    def handler(payload):
        received.append(payload)

    bus.emit("test_event", {"key": "value"})
    assert received == [{"key": "value"}]


def test_multiple_handlers_same_event():
    bus = EventBus()
    calls = []

    @bus.on("ev")
    def h1(p): calls.append(("h1", p))

    @bus.on("ev")
    def h2(p): calls.append(("h2", p))

    bus.emit("ev", 42)
    assert len(calls) == 2
    assert calls[0] == ("h1", 42)
    assert calls[1] == ("h2", 42)


def test_emit_no_handlers_no_error():
    bus = EventBus()
    bus.emit("nonexistent_event", {"data": 1})  # should not raise


def test_handlers_list():
    bus = EventBus()

    @bus.on("lifecycle")
    def on_lifecycle(p): pass

    names = bus.handlers("lifecycle")
    assert "on_lifecycle" in names


def test_handler_exception_does_not_propagate():
    bus = EventBus()

    @bus.on("boom")
    def bad_handler(p):
        raise RuntimeError("handler exploded")

    bus.emit("boom", {})  # should not raise


def test_emit_none_payload():
    bus = EventBus()
    received = []

    @bus.on("ev")
    def h(p): received.append(p)

    bus.emit("ev")
    assert received == [None]


def test_module_level_on_emit():
    from custodian import bus as bus_module
    fresh = EventBus()
    received = []

    @fresh.on("post_execute")
    def h(p): received.append(p)

    fresh.emit("post_execute", {"audit_id": "abc"})
    assert received[0]["audit_id"] == "abc"
