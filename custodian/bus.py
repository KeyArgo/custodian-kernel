from __future__ import annotations
from collections import defaultdict
from typing import Any, Callable, Dict, List
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _default_audit_handler(event: str, payload: Any) -> None:
    """Write kernel events to ~/.custodian/bus_events.log by default."""
    try:
        log_path = Path.home() / ".custodian" / "bus_events.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"{ts} {event} {payload}\n"
        with open(log_path, "a") as f:
            f.write(line)
    except Exception as e:
        # This is the sole persistence path for kernel_denied and
        # escalation_required events -- kill-switch fires, spend denials.
        # A bare `except: pass` here meant a write failure (e.g. a full
        # disk, a permissions change) made one of these vanish from the
        # audit trail with no trace anywhere: no stderr, no log, nothing.
        # Found in review.
        log.warning("EventBus failed to write audit log for event %s: %s", event, e)


class EventBus:
    """
    Publish-subscribe bus for kernel lifecycle events.

    Events emitted by the kernel:
        pre_execute          Before a @govern-wrapped function runs
        post_execute         After it completes (GovernedResult in payload)
        escalation_required  Request exceeded autonomous cap
        kernel_denied        Kill switch fired or request explicitly denied
        claim_verified       After verify_claims() completes on an output

    Usage:
        from custodian.bus import on

        @on("escalation_required")
        def notify(payload):
            send_sms(f"Escalation: ${payload['amount']} — {payload['reason']}")

        @on("kernel_denied")
        def log_denial(payload):
            audit_log.write(payload)
    """

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event: str) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self._handlers[event].append(fn)
            return fn
        return decorator

    def emit(self, event: str, payload: Any = None) -> None:
        _default_audit_handler(event, payload)
        for handler in self._handlers.get(event, []):
            try:
                handler(payload)
            except Exception as e:
                log.warning("EventBus handler %s failed for event %s: %s",
                            getattr(handler, "__name__", "?"), event, e)

    def handlers(self, event: str) -> List[str]:
        return [getattr(h, "__name__", repr(h)) for h in self._handlers.get(event, [])]


# Module-level singleton — import this, not the class
_bus = EventBus()


def on(event: str) -> Callable:
    """Register a handler on the global kernel event bus."""
    return _bus.on(event)


def emit(event: str, payload: Any = None) -> None:
    """Emit an event on the global kernel event bus."""
    _bus.emit(event, payload)
