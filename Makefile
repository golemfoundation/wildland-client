
.PHONY: all
all: update

.PHONY: update
update: env
	./env/bin/pip-sync
	./env/bin/pip install -e . plugins/*

.PHONY: compile
compile: env
	./env/bin/pip-compile --generate-hashes

env:
	python3 -m venv env/
	./env/bin/pip install -r requirements.txt
