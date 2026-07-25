.PHONY: install test lint build mutation-gate harden

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

# The guard graded against itself: the mutation gate flips each security-critical
# decision (deny/escalate/fail-closed) and proves an input catches it; the gate
# corpus replays every frozen bypass (monotonic ratchet) plus a fresh hunt.
mutation-gate:
	pytest tests/test_guard_mutation_gate.py tests/test_guard_gate_corpus.py -v

# Run the self-hardening engine: generate fresh adversarial inputs, freeze the
# caught ones into the standing corpus, and fail loudly on any that escape.
# `make harden` reports; `make harden FREEZE=1` grows the corpus.
harden:
	python scripts/harden_guard.py $(if $(FREEZE),--freeze,)

lint:
	@echo "No linter configured. Install ruff or flake8 to enable:"
	@echo "  pip install ruff && ruff check custodian/"
	@echo "  pip install flake8 && flake8 custodian/"

build:
	python -m build
	@echo "Note: install the 'build' package first: pip install build"
