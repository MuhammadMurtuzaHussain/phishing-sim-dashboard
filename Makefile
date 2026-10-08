# Shortcuts for the usual loop. Run `make help` for the list.
PY ?= python3

.DEFAULT_GOAL := help
.PHONY: help all check lint test data site serve clean

help:  ## show this list
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*##/\t/' | sort

all: check site  ## lint, test and build the dashboard

check: lint test  ## lint and test

lint:  ## ruff
	$(PY) -m ruff check .

test:  ## pytest (structure, randomisation, effects, statistics, page, drift)
	$(PY) -m pytest -q

data:  ## regenerate the dataset, assumptions and data dictionary
	$(PY) -m psim.generate
	$(PY) -m psim.docs

site:  ## build site/index.html and docs/behavioural-reading.md
	$(PY) -m psim.build

serve: site  ## build, then serve the page at http://localhost:8000
	cd site && $(PY) -m http.server 8000

clean:  ## remove build output and caches
	rm -rf site .pytest_cache .ruff_cache
