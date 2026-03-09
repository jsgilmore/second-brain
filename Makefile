SHELL := /bin/zsh
PYTHON_BIN ?= $(shell command -v python3.12 || command -v python3)
VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
SERVICE_SRC := ./second-brain-service/src
RUN_SERVICE := PYTHONPATH=$(SERVICE_SRC) $(PYTHON) -m second_brain_service.cli

.PHONY: up down logs ps setup-python mcp-stdio apply-schema rehydrate-gmail gmail-backfill gmail-backfill-resume gmail-backfill-12mo gmail-incremental ollama-pull

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

setup-python:
	$(PYTHON_BIN) -m venv $(VENV)
	$(PIP) install -r second-brain-service/requirements.txt

mcp-stdio: setup-python
	docker compose run --rm mcp python -m second_brain_service.cli serve-stdio-mcp

apply-schema: setup-python
	$(RUN_SERVICE) apply-schema

rehydrate-gmail: setup-python
	$(RUN_SERVICE) rehydrate-gmail

gmail-backfill: setup-python
	$(RUN_SERVICE) gmail-sync backfill --credentials ./config/gmail-oauth-client.json --token ./config/gmail-token.json

gmail-backfill-resume: setup-python
	$(RUN_SERVICE) gmail-sync backfill --credentials ./config/gmail-oauth-client.json --token ./config/gmail-token.json --resume

gmail-backfill-12mo: setup-python
	$(RUN_SERVICE) gmail-sync backfill --credentials ./config/gmail-oauth-client.json --token ./config/gmail-token.json --query 'newer_than:365d'

gmail-incremental: setup-python
	$(RUN_SERVICE) gmail-sync incremental --credentials ./config/gmail-oauth-client.json --token ./config/gmail-token.json

ollama-pull:
	ollama pull mxbai-embed-large
