# Convenience targets (macOS / Linux). Windows: see README "Quick start".
PY ?= .venv/bin/python

setup:
	python3 -m venv .venv && $(PY) -m pip install -r requirements-notebooks.txt

data:
	$(PY) -m python.generate_data

run:
	$(PY) pipeline.py --generate

run-offline:
	$(PY) pipeline.py --generate --offline-ai

test:
	$(PY) -m pytest -q

summary:
	$(PY) -m ai_analyst.cli summary

notebooks:
	$(PY) notebooks/build_notebooks.py

.PHONY: setup data run run-offline test summary notebooks
