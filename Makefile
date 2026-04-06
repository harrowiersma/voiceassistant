.PHONY: install run test clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
FLASK := $(VENV)/bin/flask

install:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt
	$(PYTHON) -c "from db.init_db import init_db; init_db()"
	@echo "Install complete. Run: make seed && make run"

seed:
	@test -f .env || (echo "Error: .env file not found. Copy .env.example to .env and fill in your values." && exit 1)
	$(PYTHON) scripts/seed_config.py
	@echo "Config seeded. Run: make run"

run:
	$(PYTHON) -m app

test:
	$(VENV)/bin/pytest tests/ -v

clean:
	rm -rf $(VENV) instance/

image:
	cd pi-gen && bash build.sh

image-clean:
	rm -rf pi-gen/pi-gen
