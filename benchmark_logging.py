from __future__ import annotations

import io
import json
import logging
import threading
import time
import tracemalloc
from dataclasses import dataclass

from rapidlog import Logger as FastLogger


@dataclass
class Result:
    name: str
    threads: int
    logs_per_thread: int
    total_logs: int
    elapsed_s: float
    throughput_logs_s: float
    peak_mem_kib: float


class JsonFormatter(logging.Formatter):
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


class NullBinaryIO(io.RawIOBase):
    def write(self, b: bytes) -> int:
        return len(b)

    def flush(self) -> None:
        return None


class NullTextIO(io.TextIOBase):
    def __init__(self) -> None:
        self.buffer = NullBinaryIO()

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        return None


def _run_threads(threads: int, worker) -> None:
    workers = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()


def benchmark_rapidlog(threads: int, logs_per_thread: int) -> Result:
    import sys

    real_stdout = sys.stdout
    sys.stdout = NullTextIO()
    logger = FastLogger(level="INFO", queue_size=65536, batch_size=512, thread_buffer_size=64, flush_interval=0.01)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", user_id=tid, i=i)
        logger.flush()

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    logger.close()
    sys.stdout = real_stdout
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    return Result("rapidlog", threads, logs_per_thread, total, elapsed, total / elapsed, peak / 1024)


def benchmark_stdlib_json(threads: int, logs_per_thread: int) -> Result:
    stream = NullTextIO()
    logger = logging.getLogger(f"stdlib-json-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", extra={"fields": {"user_id": tid, "i": i}})

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    return Result("stdlib+json-formatter", threads, logs_per_thread, total, elapsed, total / elapsed, peak / 1024)


def benchmark_python_json_logger(threads: int, logs_per_thread: int) -> Result | None:
    try:
        from pythonjsonlogger import jsonlogger
    except ImportError:
        return None

    stream = NullTextIO()
    logger = logging.getLogger(f"python-json-logger-{threads}-{logs_per_thread}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(jsonlogger.JsonFormatter("%(levelname)s %(message)s %(thread)d %(user_id)s %(i)s"))
    logger.addHandler(handler)

    def worker(tid: int) -> None:
        for i in range(logs_per_thread):
            logger.info("hello", extra={"user_id": tid, "i": i})

    tracemalloc.start()
    start = time.perf_counter()
    _run_threads(threads, worker)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    return Result("python-json-logger", threads, logs_per_thread, total, elapsed, total / elapsed, peak / 1024)


def run_case(threads: int, logs_per_thread: int) -> tuple[list[Result], list[str]]:
    results = [
        benchmark_rapidlog(threads, logs_per_thread),
        benchmark_stdlib_json(threads, logs_per_thread),
    ]
    notes: list[str] = []

    pj = benchmark_python_json_logger(threads, logs_per_thread)
    if pj is None:
        notes.append("python-json-logger is not installed; skipped its benchmark")
    else:
        results.append(pj)

    return results, notes


def print_table(results: list[Result], notes: list[str]) -> None:
    print("name,threads,total_logs,elapsed_s,throughput_logs_s,peak_mem_kib")
    for r in results:
        print(
            f"{r.name},{r.threads},{r.total_logs},{r.elapsed_s:.6f},{r.throughput_logs_s:.2f},{r.peak_mem_kib:.2f}"
        )
    if notes:
        print("\nnotes:")
        for note in notes:
            print(f"- {note}")


if __name__ == "__main__":
    all_results: list[Result] = []
    all_notes: set[str] = set()
    for threads, logs in [(1, 100_000), (4, 100_000)]:
        case_results, case_notes = run_case(threads, logs)
        all_results.extend(case_results)
        all_notes.update(case_notes)
    print_table(all_results, sorted(all_notes))
