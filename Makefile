.PHONY: setup lint test test-live check-sources ingest-dry

setup:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

test-live:
	uv run pytest -q -m live

check-sources:
	uv run restrooms check-sources

ingest-dry:
	uv run restrooms ingest --dry-run
