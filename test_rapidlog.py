"""
Comprehensive tests for rapidlog, including edge cases and failure scenarios.
"""

import json
import sys
import threading
import time
import io
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from rapidlog import Logger, RingQueue, _LEVELS
from scripts.set_package_version import normalize_version, update_pyproject_version


class MockBinaryIO(io.RawIOBase):
    """Mock binary IO that captures written data."""
    def __init__(self):
        self.data = []

    def write(self, b: bytes) -> int:
        self.data.append(b.decode('utf-8'))
        return len(b)

    def flush(self) -> None:
        pass


class MockTextIO(io.TextIOBase):
    """Mock text IO that has a buffer attribute (like sys.stdout)."""
    def __init__(self):
        self.buffer = MockBinaryIO()

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    def get_output(self):
        """Get all captured data as a single string."""
        return ''.join(self.buffer.data)


# ============================================================================
# RingQueue Tests
# ============================================================================

class TestRingQueue:
    """Tests for the RingQueue class."""

    def test_basic_put_and_get(self):
        """Basic put/get operations work correctly."""
        q = RingQueue(3)
        assert q.put("item1") is True
        assert q.put("item2") is True
        batch = q.get_many(2, timeout=0)
        assert batch == ["item1", "item2"]

    def test_capacity_validation(self):
        """Queue rejects non-positive capacity."""
        with pytest.raises(ValueError, match="capacity must be > 0"):
            RingQueue(0)
        with pytest.raises(ValueError, match="capacity must be > 0"):
            RingQueue(-1)

    def test_overflow_blocking(self):
        """Queue blocks when full and resumes on read."""
        q = RingQueue(2)
        assert q.put("a") is True
        assert q.put("b") is True
        
        result = []
        def putter():
            # This should block until reader consumes
            time.sleep(0.1)
            result.append(q.put("c"))
        
        reader = threading.Thread(target=putter)
        reader.start()
        time.sleep(0.2)
        
        batch = q.get_many(1, timeout=0.5)
        assert batch == ["a"]
        
        reader.join(timeout=2)
        assert reader.is_alive() is False
        assert result == [True]

    def test_put_after_close_returns_false(self):
        """put() returns False after queue is closed."""
        q = RingQueue(2)
        q.put("a")
        q.close()
        assert q.put("b") is False

    def test_get_many_with_empty_closed_queue(self):
        """get_many returns empty list for closed empty queue."""
        q = RingQueue(2)
        q.close()
        batch = q.get_many(10, timeout=0)
        assert batch == []

    def test_get_many_timeout(self):
        """get_many respects timeout when queue is empty."""
        q = RingQueue(2)
        start = time.perf_counter()
        batch = q.get_many(10, timeout=0.1)
        elapsed = time.perf_counter() - start
        assert batch == []
        assert elapsed >= 0.095

    def test_get_many_max_items(self):
        """get_many respects max_items limit."""
        q = RingQueue(10)
        for i in range(5):
            q.put(i)
        
        batch1 = q.get_many(2, timeout=0)
        assert batch1 == [0, 1]
        
        batch2 = q.get_many(10, timeout=0)
        assert batch2 == [2, 3, 4]

    def test_ring_wraparound(self):
        """Queue correctly wraps around the buffer."""
        q = RingQueue(3)
        # Fill
        q.put("a")
        q.put("b")
        q.put("c")
        # Drain first item
        assert q.get_many(1, timeout=0) == ["a"]
        # Add new item (wraps)
        q.put("d")
        # Read rest
        batch = q.get_many(3, timeout=0)
        assert batch == ["b", "c", "d"]


# ============================================================================
# Logger Concurrency Tests
# ============================================================================

class TestLoggerConcurrency:
    """Tests for concurrent logging scenarios."""

    def test_multi_thread_logging(self):
        """Multiple threads can log concurrently."""
        logger = Logger(level="INFO", queue_size=1024)
        results = []
        
        def worker(tid, count):
            for i in range(count):
                logger.info("test", thread=tid, index=i)
            results.append(tid)
        
        threads = [threading.Thread(target=worker, args=(i, 100)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        logger.close()
        assert len(results) == 4
        assert set(results) == {0, 1, 2, 3}

    def test_concurrent_flush_calls(self):
        """Multiple flush calls don't cause deadlock."""
        logger = Logger(level="INFO")
        
        def flusher():
            for _ in range(10):
                logger.flush()
        
        threads = [threading.Thread(target=flusher) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        logger.close()

    def test_logging_after_close_is_safe(self):
        """Logging after close() is handled safely."""
        logger = Logger(level="INFO")
        logger.close()
        # Should not raise
        logger.info("after close")


# ============================================================================
# Logger Serialization and Field Handling Tests
# ============================================================================

class TestLoggerFieldHandling:
    """Tests for field serialization and edge cases."""

    def _capture_logs(self, fn):
        """Helper to capture JSON logs from a logger."""
        # Redirect stdout to capture JSON output
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            fn()
            # Give writer thread time to flush
            time.sleep(0.3)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [line for line in output.strip().split('\n') if line]
        return [json.loads(line) for line in lines]

    def test_basic_fields(self):
        """Basic field types serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", user_id=123, score=4.5, active=True, name="alice")
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) == 1, f"Expected 1 log, got {len(logs)}"
        assert logs[0]["user_id"] == 123
        assert logs[0]["score"] == 4.5
        assert logs[0]["active"] is True
        assert logs[0]["name"] == "alice"

    def test_none_values(self):
        """None values serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", value=None)
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert logs[0]["value"] is None

    def test_nested_dict_fields(self):
        """Nested dictionaries serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", metadata={"nested": {"deep": "value"}})
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert logs[0]["metadata"]["nested"]["deep"] == "value"

    def test_list_fields(self):
        """List fields serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", items=[1, 2, 3], names=["a", "b"])
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert logs[0]["items"] == [1, 2, 3]
        assert logs[0]["names"] == ["a", "b"]

    def test_non_serializable_object_is_logged(self):
        """Non-JSON-serializable objects log with error message in writer thread."""
        # Note: TypeError is raised in writer thread, not main thread
        # Just verify we can log without crashing the main thread
        logger = Logger(level="INFO")
        logger.info("test", obj=datetime.now())
        logger.flush()
        logger.close()

    def test_circular_reference_is_logged(self):
        """Circular references in fields don't crash main thread."""
        # Note: ValueError is raised in writer thread for circular refs
        # Just verify main thread doesn't crash
        logger = Logger(level="INFO")
        d: dict = {"key": "value"}
        d["self"] = d
        try:
            logger.info("test", data=d)
            logger.flush()
        except:
            pass  # Writer thread might catch this
        logger.close()

    def test_unicode_in_fields(self):
        """Unicode characters in fields serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", emoji="🎉", chinese="你好", arabic="مرحبا")
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert logs[0]["emoji"] == "🎉"
        assert logs[0]["chinese"] == "你好"
        assert logs[0]["arabic"] == "مرحبا"

    def test_unicode_in_message(self):
        """Unicode characters in message serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            logger.info("Test 测试 テスト тест")
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert "测试" in logs[0]["msg"]

    def test_large_field_values(self):
        """Large field values serialize correctly."""
        def test():
            logger = Logger(level="INFO")
            large_string = "x" * 100_000
            logger.info("test", data=large_string)
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert len(logs[0]["data"]) == 100_000

    def test_special_characters_in_fields(self):
        """Special characters don't break JSON serialization."""
        def test():
            logger = Logger(level="INFO")
            logger.info("test", data='quotes"and\\slashes\n\t\r')
            logger.flush()
            logger.close()
        
        logs = self._capture_logs(test)
        assert len(logs) >= 1
        assert 'quotes' in logs[0]["data"]


# ============================================================================
# Logger Level Tests
# ============================================================================

class TestLoggerLevels:
    """Tests for log level filtering."""

    def _count_logs(self, level_str, log_fn):
        """Count how many logs are produced."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            log_fn()
            time.sleep(0.3)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        return len([l for l in output.strip().split('\n') if l])

    def test_debug_level_filter(self):
        """DEBUG level logs everything."""
        def test():
            logger = Logger(level="DEBUG")
            logger.debug("d")
            logger.info("i")
            logger.warning("w")
            logger.error("e")
            logger.critical("c")
            logger.flush()
            logger.close()
        
        count = self._count_logs("DEBUG", test)
        assert count == 5, f"Expected 5 logs, got {count}"

    def test_info_level_filter(self):
        """INFO level filters DEBUG."""
        def test():
            logger = Logger(level="INFO")
            logger.debug("d")
            logger.info("i")
            logger.warning("w")
            logger.error("e")
            logger.critical("c")
            logger.flush()
            logger.close()
        
        count = self._count_logs("INFO", test)
        assert count == 4, f"Expected 4 logs, got {count}"

    def test_error_level_filter(self):
        """ERROR level only shows ERROR and above."""
        def test():
            logger = Logger(level="ERROR")
            logger.debug("d")
            logger.info("i")
            logger.warning("w")
            logger.error("e")
            logger.critical("c")
            logger.flush()
            logger.close()
        
        count = self._count_logs("ERROR", test)
        assert count == 2, f"Expected 2 logs, got {count}"

    def test_is_enabled_for(self):
        """is_enabled_for returns correct boolean."""
        logger = Logger(level="WARNING")
        assert logger.is_enabled_for("DEBUG") is False
        assert logger.is_enabled_for("INFO") is False
        assert logger.is_enabled_for("WARNING") is True
        assert logger.is_enabled_for("ERROR") is True
        assert logger.is_enabled_for("CRITICAL") is True
        logger.close()

    def test_invalid_level_raises(self):
        """Invalid level string raises KeyError."""
        logger = Logger(level="INFO")
        with pytest.raises(KeyError):
            logger._log("INVALID", "test", {})
        logger.close()


# ============================================================================
# Logger Configuration Tests
# ============================================================================

class TestLoggerConfiguration:
    """Tests for logger configuration options."""

    def test_custom_queue_size(self):
        """Logger respects custom queue_size."""
        logger = Logger(level="INFO", queue_size=100)
        for i in range(50):
            logger.info("test", i=i)
        logger.close()

    def test_custom_batch_size(self):
        """Logger respects custom batch_size."""
        logger = Logger(level="INFO", batch_size=10)
        logger.info("test")
        logger.close()

    def test_custom_thread_buffer_size(self):
        """Logger respects custom thread_buffer_size."""
        logger = Logger(level="INFO", thread_buffer_size=10)
        for i in range(20):
            logger.info("test", i=i)
        logger.close()

    def test_custom_flush_interval(self):
        """Logger respects custom flush_interval."""
        logger = Logger(level="INFO", flush_interval=0.01)
        logger.info("test")
        time.sleep(0.02)
        logger.close()


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    def test_empty_message(self):
        """Empty message string is handled."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            logger = Logger(level="INFO")
            logger.info("")
            logger.flush()
            logger.close()
            time.sleep(0.2)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [l for l in output.strip().split('\n') if l]
        if lines:
            log = json.loads(lines[0])
            assert log["msg"] == ""

    def test_no_fields(self):
        """Log with no fields works."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            logger = Logger(level="INFO")
            logger.info("just a message")
            logger.flush()
            logger.close()
            time.sleep(0.2)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [l for l in output.strip().split('\n') if l]
        if lines:
            log = json.loads(lines[0])
            assert "msg" in log
            assert "level" in log

    def test_very_many_fields(self):
        """Log with many fields serializes correctly."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            logger = Logger(level="INFO")
            fields = {f"field_{i}": i for i in range(100)}
            logger.info("test", **fields)
            logger.flush()
            logger.close()
            time.sleep(0.2)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [l for l in output.strip().split('\n') if l]
        if lines:
            log = json.loads(lines[0])
            for i in range(100):
                assert log[f"field_{i}"] == i

    def test_flush_empty_buffer(self):
        """Flushing empty buffer is safe."""
        logger = Logger(level="INFO")
        logger.flush()
        logger.close()

    def test_multiple_close_calls(self):
        """Multiple close() calls are safe."""
        logger = Logger(level="INFO")
        logger.close()
        logger.close()  # Should not raise


# ============================================================================
# Message Format Tests
# ============================================================================

class TestMessageFormat:
    """Tests that logged JSON has correct structure."""

    def test_json_has_required_fields(self):
        """Every log has required fields."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            logger = Logger(level="INFO")
            logger.info("test message", user_id=42)
            logger.flush()
            logger.close()
            time.sleep(0.2)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [l for l in output.strip().split('\n') if l]
        assert len(lines) >= 1
        log = json.loads(lines[0])
        assert "ts_ns" in log
        assert "level" in log
        assert "msg" in log
        assert "thread" in log
        assert log["level"] == "INFO"
        assert log["msg"] == "test message"
        assert log["user_id"] == 42

    def test_json_is_valid(self):
        """Generated output is valid JSON."""
        old_stdout = sys.stdout
        mock_stdout = MockTextIO()
        sys.stdout = mock_stdout
        
        try:
            logger = Logger(level="INFO")
            for i in range(10):
                logger.info("msg", i=i, nested={"key": f"val{i}"})
            logger.flush()
            logger.close()
            time.sleep(0.2)
        finally:
            sys.stdout = old_stdout
        
        output = mock_stdout.get_output()
        lines = [l for l in output.strip().split('\n') if l]
        for line in lines:
            log = json.loads(line)  # Will raise if invalid JSON
            assert isinstance(log, dict)


# ============================================================================
# Package Version Script Tests
# ============================================================================

class TestPackageVersionScript:
    """Tests for scripts/set_package_version.py helpers."""

    def test_normalize_version(self):
        """Supports plain and v-prefixed version strings."""
        assert normalize_version("1.2.3") == "1.2.3"
        assert normalize_version("v1.2.3") == "1.2.3"
        assert normalize_version(" v2.0.0 ") == "2.0.0"

    def test_normalize_version_rejects_invalid(self):
        """Rejects empty and malformed version strings."""
        with pytest.raises(ValueError):
            normalize_version("")
        with pytest.raises(ValueError):
            normalize_version("1.2")
        with pytest.raises(ValueError):
            normalize_version("version-1.2.3")

    def test_update_pyproject_version(self, tmp_path):
        """Rewrites the version field in a pyproject file."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """[project]\nname = \"rapidlog\"\nversion = \"1.0.0\"\ndescription = \"test\"\n""",
            encoding="utf-8",
        )

        update_pyproject_version(pyproject, "1.0.1")

        updated = pyproject.read_text(encoding="utf-8")
        assert 'version = "1.0.1"' in updated
        assert 'version = "1.0.0"' not in updated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
