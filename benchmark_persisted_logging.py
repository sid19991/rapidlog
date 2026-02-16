from __future__ import annotations

import json
import logging
import threading
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

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
    bytes_written: int
    output_file: str


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


def _run_threads(threads: int, worker) -> None:
    workers = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()


def _fresh_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()


def benchmark_rapidlog_persisted(threads: int, logs_per_thread: int, out_file: Path) -> Result:
    import sys

    _fresh_file(out_file)
    real_stdout = sys.stdout

    out_handle = out_file.open("w", encoding="utf-8", buffering=1)
    sys.stdout = out_handle

    logger = FastLogger(level="INFO", queue_size=65536, batch_size=512, thread_buffer_size=64, flush_interval=0.01)

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
    return Result(
        name="rapidlog-persisted",
        threads=threads,
        logs_per_thread=logs_per_thread,
        total_logs=total,
        elapsed_s=elapsed,
        throughput_logs_s=total / elapsed,
        peak_mem_kib=peak / 1024,
        bytes_written=out_file.stat().st_size,
        output_file=str(out_file),
    )


def benchmark_stdlib_persisted(threads: int, logs_per_thread: int, out_file: Path) -> Result:
    _fresh_file(out_file)

    logger = logging.getLogger(f"stdlib-json-file-{threads}-{logs_per_thread}")
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
    logger.handlers.clear()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    return Result(
        name="stdlib-json-persisted",
        threads=threads,
        logs_per_thread=logs_per_thread,
        total_logs=total,
        elapsed_s=elapsed,
        throughput_logs_s=total / elapsed,
        peak_mem_kib=peak / 1024,
        bytes_written=out_file.stat().st_size,
        output_file=str(out_file),
    )


def benchmark_python_json_logger_persisted(threads: int, logs_per_thread: int, out_file: Path) -> Result | None:
    try:
        from pythonjsonlogger import jsonlogger
    except ImportError:
        return None

    _fresh_file(out_file)

    logger = logging.getLogger(f"python-json-logger-file-{threads}-{logs_per_thread}")
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
    logger.handlers.clear()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total = threads * logs_per_thread
    return Result(
        name="python-json-logger-persisted",
        threads=threads,
        logs_per_thread=logs_per_thread,
        total_logs=total,
        elapsed_s=elapsed,
        throughput_logs_s=total / elapsed,
        peak_mem_kib=peak / 1024,
        bytes_written=out_file.stat().st_size,
        output_file=str(out_file),
    )


def run_case(threads: int, logs_per_thread: int, output_dir: Path) -> tuple[list[Result], list[str]]:
    results = [
        benchmark_rapidlog_persisted(threads, logs_per_thread, output_dir / f"rapidlog-{threads}t.log"),
        benchmark_stdlib_persisted(threads, logs_per_thread, output_dir / f"stdlib-{threads}t.log"),
    ]
    notes: list[str] = []

    pj = benchmark_python_json_logger_persisted(
        threads,
        logs_per_thread,
        output_dir / f"python-json-logger-{threads}t.log",
    )
    if pj is None:
        notes.append("python-json-logger is not installed; skipped persisted benchmark")
    else:
        results.append(pj)

    return results, notes


def print_table(results: list[Result], notes: list[str]) -> None:
    print("name,threads,total_logs,elapsed_s,throughput_logs_s,peak_mem_kib,bytes_written,output_file")
    for r in results:
        print(
            f"{r.name},{r.threads},{r.total_logs},{r.elapsed_s:.6f},{r.throughput_logs_s:.2f},{r.peak_mem_kib:.2f},{r.bytes_written},{r.output_file}"
        )
    if notes:
        print("\nnotes:")
        for note in notes:
            print(f"- {note}")


def main() -> None:
    output_dir = Path("benchmark_logs")
    all_results: list[Result] = []
    all_notes: set[str] = set()

    for threads, logs in [(1, 50_000), (4, 50_000)]:
        case_results, case_notes = run_case(threads, logs, output_dir)
        all_results.extend(case_results)
        all_notes.update(case_notes)

    print_table(all_results, sorted(all_notes))


if __name__ == "__main__":
    main()
