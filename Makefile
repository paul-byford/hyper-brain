# hyper-brain developer tasks.
# Unix-oriented (make + a POSIX shell). Windows users can run the equivalent
# commands directly against the virtualenv under .venv/Scripts.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
TF := terraform
PROFILE ?= personal

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

.PHONY: ingest
ingest: ## Ingest configured sources into the corpus (offline, idempotent)
	$(PY) -m brain_app.ingest.run --sources config/sources.yaml --corpus corpus

.PHONY: index
index: ## Build a local index artefact from the starter corpus
	$(PY) -m brain_app.indexer.build --corpus corpus --out .brain/index.json

# --- Infrastructure (phase 5). The one-command `brain` wrapper is phase 6. ---

.PHONY: infra-validate
infra-validate: ## Validate Terraform config (offline, no cloud)
	$(TF) -chdir=infra fmt -check -recursive
	$(TF) -chdir=infra init -backend=false -input=false
	$(TF) -chdir=infra validate
	$(TF) -chdir=infra/bootstrap init -backend=false -input=false
	$(TF) -chdir=infra/bootstrap validate

.PHONY: infra-policy
infra-policy: ## Run infra policy-as-code (checkov + conftest, no cloud)
	checkov -d infra --quiet --compact
	conftest test $$(find infra -name '*.tf') -p infra/policy/security.rego
	conftest test $$(find infra -name '*.tf') --combine --namespace controlled -p infra/policy/controlled.rego

# up / down delegate to the one-command entrypoint (preflight, provision, deploy,
# seed, connect). Needs gcloud + terraform + Docker and a billing-enabled project.
.PHONY: up
up: ## Provision + deploy the brain (./brain up)
	./brain up --profile $(PROFILE)

.PHONY: down
down: ## Tear everything down (./brain down)
	./brain down --profile $(PROFILE)

.PHONY: clean
clean: ## Remove build and cache artefacts
	rm -rf $(VENV) .pytest_cache .ruff_cache .brain **/__pycache__ app/*.egg-info
