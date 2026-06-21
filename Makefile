.PHONY: install test lint build

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	@echo "No linter configured. Install ruff or flake8 to enable:"
	@echo "  pip install ruff && ruff check custodian/"
	@echo "  pip install flake8 && flake8 custodian/"

build:
	python -m build
	@echo "Note: install the 'build' package first: pip install build"
