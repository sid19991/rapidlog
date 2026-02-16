# Contributing to rapidlog

Thank you for your interest in contributing to rapidlog! We welcome contributions from the community, whether it's bug reports, feature requests, documentation, or code.

## Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/yourusername/rapidlog.git
cd rapidlog
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

### 3. Make Your Changes

Create a new branch for your work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest test_fastlog.py -v

# Run specific test class
pytest test_fastlog.py::TestRingQueue -v

# Run with coverage
pytest test_fastlog.py --cov=rapidlog --cov-report=html
```

### Running Benchmarks

```bash
# Full benchmark suite
python benchmark_enhanced.py

# Preset comparison
python demo_presets.py

# Legacy benchmarks
python benchmark_logging.py
python benchmark_persisted_logging.py
```

### Code Quality

We use **ruff** for linting and **mypy** for type checking:

```bash
# Run linter
ruff check rapidlog.py

# Run type checker
mypy rapidlog.py
```

The GitHub Actions workflows run these checks automatically on every pull request.

## Code Style

- **Python 3.10+** - We target Python 3.10 and newer
- **Type hints** - All functions should have type hints
- **Docstrings** - Use docstrings for all public classes and functions
- **Line length** - Max 100 characters (not strict, but preferred)
- **Imports** - Use absolute imports, organize with `from __future__ import annotations` at top

Example:

```python
"""Module docstring."""

from __future__ import annotations

from typing import Optional

def my_function(value: int, name: Optional[str] = None) -> str:
    """Short description.
    
    Longer description if needed.
    
    Args:
        value: Description of value
        name: Description of name (optional)
        
    Returns:
        Description of return value
    """
    # implementation
```

## Testing Requirements

- All new features should include tests
- Bug fixes should include tests that verify the fix
- Aim for comprehensive edge case coverage
- Use meaningful test names that describe what is being tested

Example test:

```python
def test_queue_respects_max_size_with_threads():
    """RingQueue should block when full with multiple producer threads."""
    queue = RingQueue(max_size=100)
    
    # Test implementation
    assert queue.size() == expected_size
```

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add support for custom serialization handlers
fix: resolve race condition in writer thread
docs: update README with migration guide
test: add edge case tests for queue wraparound
refactor: simplify JSON formatting logic
```

Use prefixes:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `test:` - Tests
- `refactor:` - Code restructuring (no behavior change)
- `perf:` - Performance improvement
- `chore:` - Maintenance tasks

## Pull Request Process

1. **Create a feature branch** from `main`
2. **Write clear PR description** - Explain what and why
3. **Reference issues** - Link to related issues (e.g., "Closes #42")
4. **Ensure tests pass** - All 37+ tests should pass
5. **Keep commits clean** - Logical, well-described commits
6. **Update docs** - Add/update documentation as needed
7. **Request review** - At least one approval required

Example PR description:

```markdown
## Description
Fixes the lock contention issue in the writer thread under high throughput.

## Changes
- Added RLock instead of Lock for thread safety
- Optimized batch flushing logic
- Added unit tests for contention scenarios

## Testing
- All 37 tests pass
- New tests for high-contention scenarios pass
- Benchmark shows 10% throughput improvement

## Related
Closes #23
```

## Areas for Contribution

### High Priority
- [ ] File rotation support
- [ ] Multiple sinks (file, network, cloud)
- [ ] Sampling (log 1-in-N records)
- [ ] Custom encoders (MessagePack, Protobuf)

### Medium Priority
- [ ] Performance optimization (Cython compilation for writer thread)
- [ ] More comprehensive benchmarks
- [ ] Framework integrations (FastAPI, Django, Flask examples)

### Documentation
- [ ] Migration guides from other libraries
- [ ] Troubleshooting guides
- [ ] Architecture deep-dive
- [ ] Performance tuning guide

### Easy (Good for first-time contributors)
- [ ] Documentation improvements
- [ ] Example projects
- [ ] README updates
- [ ] Test edge cases

## Reporting Issues

When reporting bugs, please include:

1. **Description** - What is the issue?
2. **Reproduction** - Minimal code to reproduce
3. **Expected behavior** - What should happen?
4. **Actual behavior** - What actually happens?
5. **Environment** - Python version, OS, rapidlog version

Example:

```markdown
## Bug: Logs not flushing on application exit

### Reproduction
```python
from rapidlog import get_logger
logger = get_logger()
logger.info("test")
# No flush, application exits
```

### Expected
All logs should be written to output on exit.

### Actual
Logs in buffer are lost when application exits.

### Environment
- Python 3.13
- Windows 11
- rapidlog 1.0.0
```

## Feature Requests

Include:

1. **Use case** - Why is this feature needed?
2. **Proposed solution** - How should it work?
3. **Alternatives** - Other approaches considered?

Example:

```markdown
## Feature: File rotation support

### Use case
Long-running applications generate large log files that need rotation.

### Proposed Solution
Add `max_file_size` parameter:
```python
logger = get_logger(max_file_size=100_000_000)  # 100MB
```

### Alternatives
Users could use external tools like logrotate, but built-in support would be cleaner.
```

## Code Review Process

- Reviews focus on correctness, performance, and maintainability
- Suggestions are offered as improvements, not requirements
- Approved PRs are merged into main

## Questions?

- **Discussion**: Open an issue for questions
- **Chat**: Discuss in GitHub issues
- **Documentation**: Check README and docstrings first

## Recognition

Contributors will be:
- Listed in repository credits
- Mentioned in release notes
- Recognized in community updates

Thank you for contributing to rapidlog! 🎉
