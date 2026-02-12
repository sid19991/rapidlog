# GitHub Actions & CI/CD Setup Guide

## ✅ What's Been Created

### GitHub Actions Workflows

1. **`.github/workflows/test.yml`** - Automated testing
   - Runs on: Push to main/develop, Pull Requests
   - Tests across: Ubuntu, Windows, macOS
   - Python versions: 3.10, 3.11, 3.12, 3.13
   - Generates code coverage on Ubuntu + Python 3.13

2. **`.github/workflows/benchmark.yml`** - Automated benchmarks
   - Runs on: Every Monday at 00:00 UTC (scheduled)
   - Runs on: Manual trigger (workflow_dispatch)
   - Runs on: Push to main that changes fastlog.py or benchmark_enhanced.py
   - Saves results as artifacts (90 days retention)
   - Tracks performance history over time

3. **`.github/workflows/lint.yml`** - Code quality checks
   - Runs on: Push to main/develop, Pull Requests
   - Uses: ruff (linting) and mypy (type checking)
   - Continues on error (won't block PRs)

4. **`.github/workflows/publish.yml`** - PyPI publishing
   - Runs on: GitHub Release creation
   - Manual trigger: Publishes to Test PyPI
   - Automatic: Publishes to PyPI on release

### README Badges

Added badges for:
- ✅ Tests status (GitHub Actions)
- ✅ Benchmarks status (GitHub Actions)
- ✅ Python version support
- ✅ License
- ✅ PyPI version

---

## 📋 Required Setup Steps

### 1. Enable GitHub Actions

GitHub Actions should be enabled by default. Verify at:
```
https://github.com/sid19991/fastlog/actions
```

### 2. Setup PyPI Publishing ✅ COMPLETED

1. ✅ **PyPI account created** at [pypi.org](https://pypi.org/account/register/)

2. ✅ **API token created**

3. ✅ **Token added to GitHub Secrets** as `PYPI_TOKEN`

4. ⚠️ **Package name conflict**: `fastlog` is already taken on PyPI
   - See [PACKAGE_NAMING.md](PACKAGE_NAMING.md) for alternate name suggestions
   - Update `pyproject.toml` with chosen name before publishing

5. **Optional: Test PyPI**
   - Create account at [test.pypi.org](https://test.pypi.org/account/register/)
   - Create API token
   - Add as `TEST_PYPI_TOKEN` secret
   - Test publish: Go to Actions → Publish to PyPI → Run workflow

### 3. Push the New Workflows

```bash
# Add the new workflow files
git add .github/workflows/*.yml .codecov.yml README.md

# Commit
git commit -m "ci: add GitHub Actions for tests, benchmarks, lint, and publish"

# Push to trigger first run
git push origin main
```

---

## 🚀 How to Use

### Run Tests Locally

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest test_fastlog.py -v

# Run with coverage
pytest test_fastlog.py --cov=fastlog --cov-report=html
```

### Run Benchmarks Locally

```bash
# Install benchmark dependencies
pip install structlog loguru python-json-logger

# Run benchmarks
python benchmark_enhanced.py
```

### Manual Workflow Triggers

**Trigger benchmarks manually:**
1. Go to: https://github.com/sid19991/fastlog/actions/workflows/benchmark.yml
2. Click "Run workflow"
3. Select branch
4. Click "Run workflow"

**Test PyPI publish:**
1. Go to: https://github.com/sid19991/fastlog/actions/workflows/publish.yml
2. Click "Run workflow"
3. Select branch
4. Click "Run workflow"

### Create a Release (to publish to PyPI)

```bash
# Tag the release
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# Create release on GitHub:
# https://github.com/sid19991/fastlog/releases/new
# - Tag: v1.0.0
# - Title: fastlog v1.0.0
# - Description: (release notes)
# - Click "Publish release"
```

This will automatically trigger the publish workflow.

---

## 📊 CI/CD Features

### Test Workflow
- ✅ Multi-OS testing (Ubuntu, Windows, macOS)
- ✅ Multi-version Python (3.10-3.13)
- ✅ Code coverage reporting (local only)
- ✅ Runs on every push and PR

### Benchmark Workflow
- ✅ Scheduled runs (weekly)
- ✅ Manual trigger available
- ✅ Runs on core file changes
- ✅ Saves results as artifacts
- ✅ Tracks performance history
- ✅ Adds results to job summary

### Lint Workflow
- ✅ Ruff linting (fast Python linter)
- ✅ MyPy type checking
- ✅ Non-blocking (continues on error)
- ✅ Runs on push and PR

### Publish Workflow
- ✅ Builds Python package
- ✅ Validates with twine
- ✅ Test PyPI (manual trigger)
- ✅ Production PyPI (on release)
- ✅ Requires API tokens in secrets

---

## 🔍 Monitoring

### Check Workflow Status

All workflows: https://github.com/sid19991/fastlog/actions

Individual workflows:
- Tests: https://github.com/sid19991/fastlog/actions/workflows/test.yml
- Benchmarks: https://github.com/sid19991/fastlog/actions/workflows/benchmark.yml
- Lint: https://github.com/sid19991/fastlog/actions/workflows/lint.yml
- Publish: https://github.com/sid19991/fastlog/actions/workflows/publish.yml

### Check Coverage Locally

Generate HTML coverage report:
```bash
pytest test_fastlog.py --cov=fastlog --cov-report=html
open htmlcov/index.html  # or start htmlcov/index.html on Windows
```

### View Benchmark History

Benchmark artifacts (90-day retention):
https://github.com/sid19991/fastlog/actions/workflows/benchmark.yml
- Click on any completed run
- Scroll to "Artifacts" section
- Download `benchmark-results-{sha}`

---

## 🐛 Troubleshooting

### "PyPI token invalid"
- Verify token starts with `pypi-`
- Check token scope includes upload permissions
- Regenerate token if needed

### "Benchmark workflow fails"
- Optional dependencies (structlog, loguru) might fail on some systems
- Edit `benchmark.yml` to skip problematic libraries
- fastlogging is commented out due to C extension issues on CI

### "Tests fail on Windows"
- Check file path handling (use `pathlib.Path`)
- Check line endings (Git autocrlf)
- Review test output in Actions logs

---

## 📝 Next Steps

1. **Commit and push the workflows:**
   ```bash
   git add .github/workflows/*.yml README.md
   git commit -m "ci: add GitHub Actions workflows"
   git push origin main
   ```

2. **Watch first test run** at https://github.com/sid19991/fastlog/actions

3. **Verify badges appear** in README on GitHub

4. **Setup PyPI tokens** when ready to publish (see step 2 above)

5. **Create v1.0.0 release** when ready to go live

---

**All set!** Your CI/CD pipeline is configured and ready to run. 🎉
