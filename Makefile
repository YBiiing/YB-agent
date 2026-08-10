.PHONY: test lint demo run install

install:
	python -m pip install -e .[dev]

test:
	python -m pytest tests/unit/ tests/demo/ -v

lint:
	python -m ruff check src/ tests/

demo:
	python -m pytest tests/demo/ -v

run:
	python -m src.cli.main
