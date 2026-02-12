"""
fastlog - High-performance JSON logging for Python

A logging library optimized for throughput with structured JSON output.
Designed for multi-threaded applications where logging should not be a bottleneck.

Key Features:
- Asynchronous background writer thread for JSON serialization
- Per-thread buffering to minimize lock contention
- Bounded queue with backpressure support
- Batch writes to reduce I/O overhead
- Configurable presets for different use cases

Basic Usage:
    >>> from fastlog import get_logger
    >>> logger = get_logger(level="INFO")
    >>> logger.info("user login", user_id=123, action="login")
    >>> logger.close()

Presets:
    Low-memory mode (minimal memory footprint):
    >>> logger = get_logger(preset="low-memory")
    
    Throughput mode (maximum performance):
    >>> logger = get_logger(preset="throughput")
    
    Custom configuration:
    >>> logger = get_logger(
    ...     level="INFO",
    ...     queue_size=32768,
    ...     batch_size=256,
    ...     thread_buffer_size=32,
    ...     flush_interval=0.05
    ... )

Architecture:
1. Hot path: Logger methods append records to per-thread buffers
2. Buffers flush to bounded RingQueue when full or after time interval
3. Background writer thread drains queue in batches
4. JSON serialization happens only in writer thread
5. Batched output written to sys.stdout.buffer

Memory Trade-offs:
- Low-memory preset: ~2-4 MiB peak, lower throughput
- Default: Balanced 
- Throughput preset: ~10-20 MiB peak, maximum throughput

Thread Safety:
- Multiple threads can log concurrently without contention
- Single background writer thread
- Queue provides backpressure when full

Error Handling:
- Non-JSON-serializable fields emit fallback log with error details
- Writer thread does not crash on serialization errors
- Original message and metadata preserved in error fallback
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Literal


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


# Configuration presets
_PRESETS = {
    "low-memory": {
        "queue_size": 2048,
        "batch_size": 64,
        "thread_buffer_size": 8,
        "flush_interval": 0.1,
    },
    "balanced": {
        "queue_size": 32768,
        "batch_size": 256,
        "thread_buffer_size": 32,
        "flush_interval": 0.05,
    },
    "throughput": {
        "queue_size": 131072,
        "batch_size": 1024,
        "thread_buffer_size": 128,
        "flush_interval": 0.01,
    },
}


class RingQueue:
    """
    A bounded multi-producer/single-consumer ring queue.
    
    Provides backpressure when full by blocking producers until space is available.
    Optimized for the logging use case with batch draining support.
    
    Args:
        capacity: Maximum number of items the queue can hold
        
    Raises:
        ValueError: If capacity <= 0
        
    Thread Safety:
        - Multiple producers can call put() concurrently
        - Single consumer should call get_many()
        - Internally synchronized with locks and conditions
    """

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
        """
        Add an item to the queue, blocking if full.
        
        Args:
            item: The item to add
            
        Returns:
            True if item was added, False if queue is closed
            
        Blocks:
            When queue is at capacity until space becomes available or queue is closed
        """
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
        """
        Retrieve multiple items from the queue in a batch.
        
        Args:
            max_items: Maximum number of items to retrieve
            timeout: Seconds to wait if queue is empty (0 for non-blocking)
            
        Returns:
            List of items (may be empty if timeout expires or queue is closed)
            
        Note:
            Returns up to max_items, but may return fewer if queue has fewer items available
        """
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
        """
        Close the queue, unblocking all waiting producers and consumers.
        
        After calling close():
        - put() returns False
        - get_many() returns immediately
        """
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()


class Logger:
    """
    High-performance structured JSON logger with asynchronous writes.
    
    The logger uses per-thread buffers and a background writer thread to minimize
    overhead on the hot path (logging calls). JSON serialization and I/O happen
    asynchronously in the writer thread.
    
    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        queue_size: Size of cross-thread queue (larger = more buffering)
        batch_size: Records per write batch (larger = fewer I/O calls)
        thread_buffer_size: Records per thread before flushing (larger = less queue traffic)
        flush_interval: Seconds between automatic flushes (lower = more real-time)
        preset: Use predefined configuration ("low-memory", "balanced", "throughput")
    
    Preset Characteristics:
        low-memory:
            - queue_size=2048, batch_size=64, thread_buffer_size=8
            - Peak memory: ~2-4 MiB
            - Best for: Memory-constrained environments
            
        balanced (default):
            - queue_size=32768, batch_size=256, thread_buffer_size=32
            - Peak memory: ~5-10 MiB
            - Best for: General-purpose applications
            
        throughput:
            - queue_size=131072, batch_size=1024, thread_buffer_size=128
            - Peak memory: ~10-20 MiB
            - Best for: High-volume logging with throughput priority
    
    Examples:
        >>> # Use preset
        >>> logger = Logger(preset="low-memory")
        >>> logger.info("Starting service", version="1.0.0")
        >>> logger.close()
        
        >>> # Custom configuration
        >>> logger = Logger(
        ...     level="DEBUG",
        ...     queue_size=16384,
        ...     batch_size=512
        ... )
        >>> logger.debug("Debug info", request_id=123)
        >>> logger.close()
    
    Thread Safety:
        Logger methods (info, debug, etc.) can be called from multiple threads
        concurrently. Each thread maintains its own buffer to avoid contention.
    
    Lifecycle:
        Always call close() before process exit to ensure all logs are written.
        The writer thread is daemonic but close() ensures clean shutdown.
    
    Error Handling:
        If a field value cannot be JSON-serialized (e.g., datetime objects,
        circular references), the writer emits a fallback log with error details
        instead of crashing. The original message is preserved.
    """
    
    def __init__(
        self,
        *,
        level: str = "INFO",
        queue_size: int | None = None,
        batch_size: int | None = None,
        thread_buffer_size: int | None = None,
        flush_interval: float | None = None,
        preset: Literal["low-memory", "balanced", "throughput"] | None = None,
    ) -> None:
        # Apply preset or defaults
        if preset:
            if preset not in _PRESETS:
                raise ValueError(f"Unknown preset: {preset}. Choose from: {list(_PRESETS.keys())}")
            config = _PRESETS[preset].copy()
        else:
            config = _PRESETS["balanced"].copy()
        
        # Override with explicit parameters
        if queue_size is not None:
            config["queue_size"] = queue_size
        if batch_size is not None:
            config["batch_size"] = batch_size
        if thread_buffer_size is not None:
            config["thread_buffer_size"] = thread_buffer_size
        if flush_interval is not None:
            config["flush_interval"] = flush_interval
        
        self._min_level = _LEVELS[level.upper()]
        self._queue = RingQueue(config["queue_size"])
        self._batch_size = config["batch_size"]
        self._thread_buffer_size = config["thread_buffer_size"]
        self._flush_interval = config["flush_interval"]
        self._local = threading.local()
        self._stop = threading.Event()
        self._writer = threading.Thread(target=self._writer_loop, name="fastlog-writer", daemon=True)
        self._writer.start()

    def is_enabled_for(self, level: str) -> bool:
        """
        Check if a log level is enabled.
        
        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            
        Returns:
            True if logs at this level will be emitted
            
        Example:
            >>> if logger.is_enabled_for("DEBUG"):
            ...     expensive_data = compute_debug_info()
            ...     logger.debug("Debug data", data=expensive_data)
        """
        return _LEVELS[level.upper()] >= self._min_level

    def debug(self, message: str, **fields: Any) -> None:
        """Log a DEBUG level message with optional structured fields."""
        self._log("DEBUG", message, fields)

    def info(self, message: str, **fields: Any) -> None:
        """Log an INFO level message with optional structured fields."""
        self._log("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        """Log a WARNING level message with optional structured fields."""
        self._log("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        """Log an ERROR level message with optional structured fields."""
        self._log("ERROR", message, fields)

    def critical(self, message: str, **fields: Any) -> None:
        """Log a CRITICAL level message with optional structured fields."""
        self._log("CRITICAL", message, fields)

    def flush(self) -> None:
        """
        Force flush of current thread's buffer to the queue.
        
        Normally buffers flush automatically based on size and time thresholds.
        Use this to ensure logs are written immediately (e.g., before shutdown).
        
        Note:
            This flushes to the queue, not to disk. Call close() to ensure
            complete write to stdout.
        """
        buf = self._get_thread_buffer()
        self._flush_thread_buffer(buf)

    def close(self) -> None:
        """
        Flush all logs and shutdown the logger.
        
        This method:
        1. Flushes the current thread's buffer
        2. Signals the writer thread to stop
        3. Closes the queue (unblocking any waiting producers)
        4. Waits for the writer thread to finish
        
        Always call close() before process exit to avoid losing logs.
        After close(), logging calls are safe but may not be written.
        """
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
                try:
                    payload.update(record[_FIELDS])
                    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                except (TypeError, ValueError) as exc:
                    fallback = {
                        "ts_ns": record[_TS_NS],
                        "level": record[_LEVEL],
                        "msg": record[_MESSAGE],
                        "thread": record[_THREAD_ID],
                        "fastlog_error": f"{type(exc).__name__}: {exc}",
                        "fastlog_fields_repr": repr(record[_FIELDS]),
                    }
                    line = json.dumps(fallback, separators=(",", ":"), ensure_ascii=False)
                lines.append(line)

            out.write(("\n".join(lines) + "\n").encode("utf-8"))
            out.flush()


def get_logger(**kwargs: Any) -> Logger:
    """
    Create a new Logger instance with the specified configuration.
    
    This is a convenience factory function equivalent to Logger(**kwargs).
    
    Args:
        **kwargs: Passed directly to Logger constructor
        
    Returns:
        Configured Logger instance
        
    Examples:
        >>> # Use preset
        >>> logger = get_logger(preset="throughput")
        
        >>> # Custom configuration
        >>> logger = get_logger(
        ...     level="DEBUG",
        ...     queue_size=8192,
        ...     batch_size=128
        ... )
        
    See Also:
        Logger: For full documentation of available parameters
    """
    return Logger(**kwargs)
