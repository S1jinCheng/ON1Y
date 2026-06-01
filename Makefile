.PHONY: install dev test lint init ingest

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check on1y tests scripts

init:
	on1y init

ingest:
	@test -n "$(URL)" || (echo "Usage: make ingest URL=https://example.com" && exit 1)
	on1y ingest "$(URL)"
