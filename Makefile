SHELL := /bin/bash
IN_DOCKER := $(shell if test -z $(WL_ENV); then echo 0; else echo 1; fi)

ifeq ($(IN_DOCKER), 1)
VENV_BIN=/home/user/env/bin
REQUIREMENTS_ENV=$(WL_ENV)
PIP_INSTALL_FLAGS=
else
VENV_BIN=./env/bin
REQUIREMENTS_ENV=dev
PIP_INSTALL_FLAGS=-e
endif

.PHONY: all
all: update

.PHONY: update
update: env base plugins

.PHONY: base
base:
	$(VENV_BIN)/pip-sync requirements.$(REQUIREMENTS_ENV).txt
	$(VENV_BIN)/pip install $(PIP_INSTALL_FLAGS) .

.PHONY: plugins
plugins:
	for m in plugins/*; do $(VENV_BIN)/pip install $(PIP_INSTALL_FLAGS) $$m; done

.PHONY: compile
compile: env
	rm -f requirements.base.txt requirements.dev.txt requirements.ci.txt
	$(VENV_BIN)/pip-compile --generate-hashes --output-file requirements.base.txt requirements.base.in
	$(VENV_BIN)/pip-compile --generate-hashes --output-file requirements.dev.txt requirements.dev.in
	$(VENV_BIN)/pip-compile --generate-hashes --output-file requirements.ci.txt requirements.ci.in

.PHONY: env
ifeq ($(IN_DOCKER), 1)
env:
	$(VENV_BIN)/python3 -m pip install --upgrade pip
	$(VENV_BIN)/pip install -r requirements.$(REQUIREMENTS_ENV).txt
else
env:
	python3 -m venv env/
	$(VENV_BIN)/python3 -m pip install --upgrade pip
	$(VENV_BIN)/pip install -r requirements.$(REQUIREMENTS_ENV).txt
endif
