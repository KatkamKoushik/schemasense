"""Sequenced Server-Sent Events (SSE) Engine for SchemaSense 2.0.

Provides durable, monotonic event sequencing, W3C-compliant frame formatting,
and seamless reconnection and replay via Last-Event-ID.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("schemasense.api.events")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SSEEvent(BaseModel):
    """A sequenced Server-Sent Event conforming to the W3C SSE standard."""

    model_config = ConfigDict(extra="ignore")

    event_id: int
    run_id: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now_iso)

    def to_sse_frame(self) -> str:
        """Formats the event into a standard text/event-stream frame."""
        serialized_data = json.dumps(self.data, default=str)
        return (
            f"id: {self.event_id}\n"
            f"event: {self.event_type}\n"
            f"data: {serialized_data}\n\n"
        )


class EventStore:
    """Thread-safe and async-safe sequenced event store with replay support.

    Maintains a sequenced buffer of events per run_id, allowing clients
    reconnecting with `Last-Event-ID` to replay missed events before receiving live updates.
    """

    def __init__(self, max_buffer_per_run: int = 500) -> None:
        self.max_buffer_per_run = max_buffer_per_run
        self._buffers: dict[str, list[SSEEvent]] = defaultdict(list)
        self._counters: dict[str, int] = defaultdict(int)
        self._subscribers: dict[str, set[asyncio.Queue[SSEEvent | None]]] = defaultdict(
            set
        )
        self._closed_runs: set[str] = set()
        self._lock = threading.RLock()

    def record_event(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> SSEEvent:
        """Records a new sequenced event and broadcasts it to active subscribers."""
        clean_data = dict(data or {})
        # Sanitize sensitive fields (zero secret leakage)
        for key in list(clean_data.keys()):
            lower = key.lower()
            if any(
                secret_word in lower
                for secret_word in ("password", "secret", "token", "key", "uri")
            ):
                clean_data[key] = "[REDACTED]"

        with self._lock:
            self._counters[run_id] += 1
            event_id = self._counters[run_id]

            event = SSEEvent(
                event_id=event_id,
                run_id=run_id,
                event_type=event_type,
                data=clean_data,
                timestamp=_utc_now_iso(),
            )

            # Store in ring buffer
            buffer = self._buffers[run_id]
            buffer.append(event)
            if len(buffer) > self.max_buffer_per_run:
                buffer.pop(0)

            # Notify active subscribers
            active_queues = list(self._subscribers[run_id])

        for q in active_queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Subscriber queue full for run '%s'; dropping live frame.", run_id
                )

        return event

    def close_stream(self, run_id: str) -> None:
        """Signals end-of-stream to all active subscribers for the run."""
        with self._lock:
            self._closed_runs.add(run_id)
            active_queues = list(self._subscribers[run_id])
        for q in active_queues:
            try:
                q.put_nowait(None)
            except Exception:  # noqa: BLE001
                pass

    def get_events(self, run_id: str, since_id: int = 0) -> list[SSEEvent]:
        """Retrieves all buffered events for a run with event_id > since_id (for replay)."""
        with self._lock:
            buffer = self._buffers.get(run_id, [])
            return [e for e in buffer if e.event_id > since_id]

    async def subscribe(
        self,
        run_id: str,
        since_id: int = 0,
        heartbeat_interval_sec: float = 15.0,
    ) -> AsyncGenerator[str, None]:
        """Async generator yielding SSE frames, starting with replay of missed events."""
        # 1. Replay missed events from buffer
        replay_events = self.get_events(run_id, since_id=since_id)
        for past_event in replay_events:
            yield past_event.to_sse_frame()

        with self._lock:
            if run_id in self._closed_runs:
                return

            # 2. Register queue for live events
            queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=100)
            self._subscribers[run_id].add(queue)

        try:
            while True:
                try:
                    live_event: SSEEvent | None = await asyncio.wait_for(
                        queue.get(),
                        timeout=heartbeat_interval_sec,
                    )
                    if live_event is None:
                        # End of stream signaled
                        break
                    yield live_event.to_sse_frame()
                except asyncio.TimeoutError:
                    # Emit periodic comment heartbeat to keep connection alive
                    yield ": ping\n\n"
        finally:
            with self._lock:
                self._subscribers[run_id].discard(queue)

    def clear(self) -> None:
        """Clears all buffered events and subscribers (used in test cleanup)."""
        with self._lock:
            self._buffers.clear()
            self._counters.clear()
            self._subscribers.clear()
            self._closed_runs.clear()
            self._counters.clear()
            self._subscribers.clear()


# Global Singleton Event Store
_GLOBAL_EVENT_STORE: EventStore = EventStore()


def get_event_store() -> EventStore:
    """Returns the platform singleton event store."""
    return _GLOBAL_EVENT_STORE
