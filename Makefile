.PHONY: test lint check self-test clean

PYTHON ?= $(shell command -v python3 >/dev/null 2>&1 && echo python3 || echo "uv run --no-project python")
PYTHONPATH := .

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

self-test: test

lint:
	@which ruff >/dev/null 2>&1 && ruff check band tests || echo "ruff not installed, skipping python lint"

check: test lint
	@echo "==> Band test suite is clean and passing."

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pipeline_state.json .done_cache.json
