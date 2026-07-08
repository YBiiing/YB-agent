.PHONY: test lint demo run install

install:
	pip install -e .[dev]

test:
	pytest tests/unit/ -v

lint:
	ruff check src/ tests/

demo:
	pytest tests/demo/ -v

run:
	python -m src.cli.main