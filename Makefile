# hyper-brain developer tasks.
# Unix-oriented (make + a POSIX shell). Windows users can run the equivalent
# commands directly against the virtualenv under .venv/Scripts.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(VENV): ## Create the virtualenv
	python3 -m venv $(VENV)

.PHONY: install
install: $(VENV) ## Install the app with dev tools
	$(PIP) install --upgrade pip
	$(PIP) install -e ./app[dev]

.PHONY: fmt
fmt: ## Auto-format
	$(VENV)/bin/ruff format app

.PHONY: lint
lint: ## Lint
	$(VENV)/bin/ruff check app
	$(VENV)/bin/ruff format --check app

.PHONY: test
test: ## Run the full test suite
	$(PY) -m pytest app/tests -q

.PHONY: eval
eval: ## Run the offline AI eval tier
	$(PY) -m pytest app/tests -q -m eval

.PHONY: security
security: ## Run the security pillar (SAST + dependency audit)
	$(VENV)/bin/bandit -q -r app/brain_app
	$(VENV)/bin/pip-audit -r app/requirements.txt || true

.PHONY: index
index: ## Build a local index artefact from the starter corpus
	$(PY) -m brain_app.indexer.build --corpus corpus --out .brain/index.json

# Provisioning targets (implemented in phases 4 and 5; see IMPLEMENTATION-PLAN.md).
.PHONY: up down
up down: ## Provision / tear down (not yet implemented)
	@echo "Not implemented yet. See IMPLEMENTATION-PLAN.md phases 4-5 (the ./brain entrypoint)."

.PHONY: clean
clean: ## Remove build and cache artefacts
	rm -rf $(VENV) .pytest_cache .ruff_cache .brain **/__pycache__ app/*.egg-info
