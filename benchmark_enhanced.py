"""
Benchmark comparing rapidlog against multiple logging libraries with actual file I/O.
Includes stdlib, structlog, loguru, python-json-logger, and fastlogging.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rapidlog import Logger as RapidLogger


BENCHMARK_DIR = Path("benchmark_logs")


@dataclass
class Result:
    name: str
    threads: int
    logs_per_thread: int
    total_logs: int
    elapsed_s: float
    throughput_logs_s: float
    peak_mem_mib: float
    bytes_written: int
    output_file: str


class JsonFormatter(logging.Formatter):
    """JSON formatter for stdlib logging."""
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts_ns": time.time_ns(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "thread": record.thread,
        }
        if hasattr(record, "fields") and isinstance(record.fields, dict):
            payload.update(record.fields)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


class BatchingHandler(logging.Handler):
    """A simple batching handler that collects logs before writing."""
    def __init__(self, stream, batch_size: int = 256):
        super().__init__()
        self.stream = stream
        self.batch_size = batch_size
        self.batch = []
        self.lock = threading.RLock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self.lock:
                self.batch.append(msg)
                if len(self.batch) >= self.batch_size:
                    self.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        with self.lock:
            if self.batch:
                for msg in self.batch:
                    self.stream.write(msg + "\n")
                self.stream.flush()
                self.batch.clear()


def _fresh_file(path: Path) -> None:
    """Create a fresh log file, removing if it exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()


def _run_threads(threads: int, worker: Callable[[int], None]) -> None:
    """Run worker function in multiple threads."""
    workers = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()


def benchmark_rapidlog(threads: int, logs_per_thread: int) -> Result:
    """Benchmark rapidlog library with file output."""
    out_file = BENCHMARK_DIR / f"rapidlog-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    real_stdout = sys.stdout
    out_handle = out_file.open("w", encoding="utf-8", buffering=1)
    sys.stdout = out_handle
    
    logger = RapidLogger(
        level="INFO",
        queue_size=65536,
        batch_size=512,
        thread_buffer_size=64,
        flush_interval=0.01,
    )

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", user_id=tid, i=i)
        logger.flush()

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    logger.close()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    sys.stdout = real_stdout
    out_handle.close()
    
    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "rapidlog",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_stdlib_basic(threads: int, logs_per_thread: int) -> Result:
    """Benchmark stdlib logging with basic config."""
    out_file = BENCHMARK_DIR / f"stdlib-basic-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    logger = logging.getLogger(f"stdlib-basic-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    
    handler = logging.FileHandler(out_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello")

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    handler.flush()
    handler.close()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "stdlib-basic",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_stdlib_json(threads: int, logs_per_thread: int) -> Result:
    """Benchmark stdlib logging with JSON formatter."""
    out_file = BENCHMARK_DIR / f"stdlib-json-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    logger = logging.getLogger(f"stdlib-json-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    
    handler = logging.FileHandler(out_file, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", extra={"fields": {"user_id": tid, "i": i}})

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    handler.flush()
    handler.close()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "stdlib-json",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_stdlib_batching(threads: int, logs_per_thread: int) -> Result:
    """Benchmark stdlib logging with custom batching handler."""
    out_file = BENCHMARK_DIR / f"stdlib-batching-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    file_stream = out_file.open("w", encoding="utf-8", buffering=1)
    logger = logging.getLogger(f"stdlib-batching-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    
    handler = BatchingHandler(file_stream, batch_size=256)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", extra={"fields": {"user_id": tid, "i": i}})

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    handler.flush()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    file_stream.close()
    
    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "stdlib-batching",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_python_json_logger(threads: int, logs_per_thread: int) -> Result | None:
    """Benchmark python-json-logger library."""
    try:
        from pythonjsonlogger import jsonlogger
    except ImportError:
        return None

    out_file = BENCHMARK_DIR / f"python-json-logger-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    logger = logging.getLogger(f"python-json-logger-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    
    handler = logging.FileHandler(out_file, encoding="utf-8")
    handler.setFormatter(jsonlogger.JsonFormatter("%(levelname)s %(message)s %(thread)d %(user_id)s %(i)s"))
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", extra={"user_id": tid, "i": i})

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    handler.flush()
    handler.close()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "python-json-logger",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_structlog_json(threads: int, logs_per_thread: int) -> Result | None:
    """Benchmark structlog with JSON rendering."""
    try:
        import structlog
    except ImportError:
        return None

    out_file = BENCHMARK_DIR / f"structlog-json-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    # Configure structlog for JSON file output
    file_stream = out_file.open("w", encoding="utf-8", buffering=1)
    structlog.configure(
        processors=[
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=file_stream),
    )

    def worker(tid: int) -> None:
        logger = structlog.get_logger()
        for i in range(logs_per_thread):
            logger.info("hello", user_id=tid, i=i)

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    file_stream.flush()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    file_stream.close()
    
    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "structlog-json",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_loguru(threads: int, logs_per_thread: int) -> Result | None:
    """Benchmark loguru with minimal JSON output (comparable to rapidlog)."""
    try:
        from loguru import logger as loguru_logger
    except ImportError:
        return None

    out_file = BENCHMARK_DIR / f"loguru-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    # Custom sink for minimal JSON output (similar to rapidlog)
    file_handle = out_file.open("w", encoding="utf-8", buffering=1)
    
    def minimal_json_handler(message):
        """Custom handler that outputs minimal JSON comparable to rapidlog."""
        record = message.record
        payload = {
            "ts_ns": int(record["time"].timestamp() * 1_000_000_000),
            "level": record["level"].name,
            "msg": record["message"],
            "thread": record["thread"].id,
            **record["extra"]
        }
        file_handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    
    # Remove default handler and add custom minimal JSON handler
    loguru_logger.remove()
    loguru_logger.add(minimal_json_handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            loguru_logger.bind(user_id=tid, i=i).info("hello")

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    file_handle.flush()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    file_handle.close()

    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size
    return Result(
        "loguru",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def benchmark_fastlogging(threads: int, logs_per_thread: int) -> Result | None:
    """Benchmark fastlogging library with file output.
    
    NOTE: fastlogging does NOT output structured JSON. It outputs text format:
    "2026-02-13 10:15:30.123 INFO: {\"msg\": \"hello\", ...}"
    Manual JSON encoding is required, and output is NOT parseable as pure JSON.
    Not directly comparable as a structured logging solution.
    """
    try:
        import fastlogging
    except ImportError:
        return None

    out_file = BENCHMARK_DIR / f"fastlogging-{threads}x{logs_per_thread}.jsonl"
    _fresh_file(out_file)
    
    # Configure fastlogging with file output
    logger = fastlogging.LogInit(
        pathName=str(out_file),
        console=False,
        colors=False,
        encoding="utf-8"
    )
    logger.level = fastlogging.INFO

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            # fastlogging doesn't have native structured logging,
            # so we format as JSON manually (still outputs text format, not pure JSON)
            import json
            msg = json.dumps({"msg": "hello", "user_id": tid, "i": i})
            logger.info(msg)

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    logger.flush()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    logger.shutdown()

    total = threads * logs_per_thread
    bytes_written = out_file.stat().st_size if out_file.exists() else 0
    return Result(
        "fastlogging",
        threads,
        logs_per_thread,
        total,
        elapsed,
        total / elapsed,
        peak / 1024 / 1024,
        bytes_written,
        str(out_file),
    )


def run_case(threads: int, logs_per_thread: int) -> tuple[list[Result], list[str]]:
    """Run a benchmark case across all loggers."""
    results = [
        benchmark_rapidlog(threads, logs_per_thread),
        benchmark_stdlib_basic(threads, logs_per_thread),
        benchmark_stdlib_json(threads, logs_per_thread),
        benchmark_stdlib_batching(threads, logs_per_thread),
    ]
    notes: list[str] = []

    # Optional libraries
    pj = benchmark_python_json_logger(threads, logs_per_thread)
    if pj is None:
        notes.append("python-json-logger not installed; skipped")
    else:
        results.append(pj)

    sl = benchmark_structlog_json(threads, logs_per_thread)
    if sl is None:
        notes.append("structlog not installed; skipped")
    else:
        results.append(sl)

    lg = benchmark_loguru(threads, logs_per_thread)
    if lg is None:
        notes.append("loguru not installed; skipped")
    else:
        results.append(lg)

    fl = benchmark_fastlogging(threads, logs_per_thread)
    if fl is None:
        notes.append("fastlogging not installed; skipped")
    else:
        results.append(fl)

    return results, notes


def print_table(results: list[Result], notes: list[str]) -> None:
    """Print results as CSV."""
    print("name,threads,total_logs,elapsed_s,throughput_logs_s,peak_mem_mib,bytes_written,output_file")
    for r in results:
        print(
            f"{r.name},{r.threads},{r.total_logs},{r.elapsed_s:.6f},"
            f"{r.throughput_logs_s:.2f},{r.peak_mem_mib:.2f},{r.bytes_written},{r.output_file}"
        )
    if notes:
        print("\nnotes:")
        for note in notes:
            print(f"- {note}")
    
    # Add benchmark fairness notes
    print("\nOutput Format Information:")
    print("- rapidlog, stdlib-json, structlog, python-json-logger, loguru: Minimal JSON (~100 bytes/log)")
    print("- fastlogging: NOT structured JSON (text format with embedded JSON string)")
    print("\nAll libraries output comparable JSON formats (except fastlogging)")
    print("Note: bytes_written column shows actual output size for verification")


if __name__ == "__main__":
    print("Running benchmarks with actual file I/O...")
    print("=" * 80)
    
    all_results: list[Result] = []
    all_notes: set[str] = set()
    
    # Run multiple cases
    cases = [
        (1, 100_000),   # Single thread
        (4, 100_000),   # Multi-threaded
        (8, 50_000),    # Heavy multi-threaded
    ]
    
    for threads, logs in cases:
        print(f"\nCase: {threads} thread(s), {logs:,} logs per thread")
        print("-" * 80)
        case_results, case_notes = run_case(threads, logs)
        all_results.extend(case_results)
        all_notes.update(case_notes)
    
    print("\n" + "=" * 80)
    print("Summary:")
    print_table(all_results, sorted(all_notes))
    print("\nNote: All measurements include actual file I/O with line buffering.")
    print(f"Log files written to: {BENCHMARK_DIR.absolute()}")
