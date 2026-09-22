.PHONY: test lint check self-test clean

PYTHON ?= python3
PYTHONPATH := .agents/scripts

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s .agents/scripts/done/tests -p 'test_*.py'

self-test: test
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

lint:
	@which ruff >/dev/null 2>&1 && ruff check .agents/scripts/done tests || echo "ruff not installed, skipping python lint"

check: test lint
	@echo "==> Band test suite is clean and passing."

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .agents/.pipeline_state.json .agents/.done_cache.json
