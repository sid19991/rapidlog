# fastlog

`fastlog` is an experiment in building a **high-performance JSON logging library for Python** with a narrow initial scope.

## What we are trying to build

The goal is a logger that is faster than common Python JSON-logging setups while keeping a simple API:

```python
logger.info("user login", user_id=123)
```

### Design goals

- Faster than `structlog` and `logging + json-logger`
- Treat JSON as an **output format**, not the internal hot-path format
- Avoid dict creation on the hot path where possible
- Avoid per-log allocation where possible
- Defer JSON serialization
- Batch writes
- Stdout sink only (v1)

### Constraints (v1)

- Python 3.10+
- No external runtime dependencies
- No async user-facing API
- Single writer thread allowed
- Thread-safe logging from multiple producer threads

## Current architecture

The implementation in `fastlog.py` currently follows this shape:

1. **Hot path (`Logger._log`)**
   - Level check first.
   - Build a compact array/list record with fixed slots.
   - Append to a per-thread buffer.
2. **Cross-thread handoff**
   - Per-thread buffers flush into a bounded `RingQueue`.
   - Queue is multi-producer / single-consumer.
3. **Writer thread**
   - Background writer drains records in batches.
   - JSON serialization happens only in writer thread.
   - Batch is written to `sys.stdout.buffer`.

## Repository layout

- `fastlog.py` — core logger + queue + writer thread.
- `benchmark_logging.py` — in-memory benchmark (no real file persistence).
- `benchmark_persisted_logging.py` — production-style benchmark with logs persisted to files.

## Running benchmarks

### 1) In-memory benchmark

```bash
python benchmark_logging.py
```

This compares pipeline overhead while minimizing output-device effects.

### 2) Persisted benchmark

```bash
python benchmark_persisted_logging.py
```

This writes real log files under `benchmark_logs/` and reports throughput/time/memory with actual persistence.

## Project status

This is intentionally minimal and focused on validating core architecture and performance trade-offs.
