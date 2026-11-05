# On Windows the recipes run under cmd.exe so the venv path with backslashes works.
ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
PY ?= .venv\Scripts\python.exe
else
PY ?= .venv/bin/python
endif

MODEL ?=
MODEL_ARG = $(if $(MODEL),--model $(MODEL),)

.PHONY: up down seed index test eval eval-smoke eval-adversarial chat slack sync dashboard console-setup console

up:
	docker compose up -d --wait

down:
	docker compose down

seed:
	$(PY) -m app.db seed

index:
	$(PY) -m app.retrieval build

test:
	$(PY) -m pytest -q

eval:
	$(PY) evals/run_evals.py $(MODEL_ARG)

eval-smoke:
	$(PY) evals/run_evals.py --smoke $(MODEL_ARG)

eval-adversarial:
	$(PY) evals/run_evals.py --adversarial $(MODEL_ARG)

chat:
	$(PY) -m app.cli

slack:
	$(PY) -m app.slack_bot

sync:
	$(PY) -m app.sync

dashboard:
	$(PY) -m streamlit run dashboard/app.py

console-setup:
	$(PY) manage.py migrate
	$(PY) manage.py setup_roles

console:
	$(PY) manage.py runserver
