from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any


_TS_NS = 0
_LEVEL = 1
_MESSAGE = 2
_FIELDS = 3
_THREAD_ID = 4


_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


class RingQueue:
    """A bounded multi-producer/single-consumer ring queue."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._capacity = capacity
        self._buffer: list[Any] = [None] * capacity
        self._head = 0
        self._tail = 0
        self._size = 0
        self._closed = False
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)

    def put(self, item: Any) -> bool:
        with self._not_full:
            while self._size == self._capacity and not self._closed:
                self._not_full.wait()
            if self._closed:
                return False
            self._buffer[self._tail] = item
            self._tail = (self._tail + 1) % self._capacity
            self._size += 1
            self._not_empty.notify()
            return True

    def get_many(self, max_items: int, timeout: float) -> list[Any]:
        with self._not_empty:
            if self._size == 0 and not self._closed:
                self._not_empty.wait(timeout=timeout)
            if self._size == 0:
                return []

            take = self._size if self._size < max_items else max_items
            out = [None] * take
            for i in range(take):
                out[i] = self._buffer[self._head]
                self._buffer[self._head] = None
                self._head = (self._head + 1) % self._capacity
            self._size -= take
            self._not_full.notify_all()
            return out

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()


class Logger:
    def __init__(
        self,
        *,
        level: str = "INFO",
        queue_size: int = 32768,
        batch_size: int = 256,
        thread_buffer_size: int = 32,
        flush_interval: float = 0.05,
    ) -> None:
        self._min_level = _LEVELS[level.upper()]
        self._queue = RingQueue(queue_size)
        self._batch_size = batch_size
        self._thread_buffer_size = thread_buffer_size
        self._flush_interval = flush_interval
        self._local = threading.local()
        self._stop = threading.Event()
        self._writer = threading.Thread(target=self._writer_loop, name="fastlog-writer", daemon=True)
        self._writer.start()

    def is_enabled_for(self, level: str) -> bool:
        return _LEVELS[level.upper()] >= self._min_level

    def debug(self, message: str, **fields: Any) -> None:
        self._log("DEBUG", message, fields)

    def info(self, message: str, **fields: Any) -> None:
        self._log("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._log("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        self._log("ERROR", message, fields)

    def critical(self, message: str, **fields: Any) -> None:
        self._log("CRITICAL", message, fields)

    def flush(self) -> None:
        buf = self._get_thread_buffer()
        self._flush_thread_buffer(buf)

    def close(self) -> None:
        self.flush()
        self._stop.set()
        self._queue.close()
        self._writer.join()

    def _get_thread_buffer(self) -> list[list[Any]]:
        buf = getattr(self._local, "buffer", None)
        if buf is None:
            buf = []
            self._local.buffer = buf
            self._local.last_flush = time.perf_counter()
        return buf

    def _log(self, level: str, message: str, fields: dict[str, Any]) -> None:
        if _LEVELS[level] < self._min_level:
            return

        record = [
            time.time_ns(),
            level,
            message,
            fields,
            threading.get_ident(),
        ]

        buf = self._get_thread_buffer()
        buf.append(record)

        should_flush = len(buf) >= self._thread_buffer_size
        if not should_flush:
            now = time.perf_counter()
            if now - self._local.last_flush >= self._flush_interval:
                should_flush = True

        if should_flush:
            self._flush_thread_buffer(buf)
            self._local.last_flush = time.perf_counter()

    def _flush_thread_buffer(self, buf: list[list[Any]]) -> None:
        if not buf:
            return
        for record in buf:
            self._queue.put(record)
        buf.clear()

    def _writer_loop(self) -> None:
        out = sys.stdout.buffer
        while True:
            batch = self._queue.get_many(self._batch_size, timeout=self._flush_interval)
            if not batch:
                if self._stop.is_set():
                    break
                continue

            lines = []
            for record in batch:
                payload = {
                    "ts_ns": record[_TS_NS],
                    "level": record[_LEVEL],
                    "msg": record[_MESSAGE],
                    "thread": record[_THREAD_ID],
                }
                payload.update(record[_FIELDS])
                lines.append(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))

            out.write(("\n".join(lines) + "\n").encode("utf-8"))
            out.flush()


def get_logger(**kwargs: Any) -> Logger:
    return Logger(**kwargs)
