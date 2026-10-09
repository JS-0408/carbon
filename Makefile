.PHONY: install test bench demo run clean docker-build docker-up

VENV = .venv
PYTHON = $(VENV)/Scripts/python
UVICORN = $(VENV)/Scripts/uvicorn
PYTEST = $(VENV)/Scripts/pytest

# Fallback for unix-style environments if needed
ifeq ($(OS),Windows_NT)
    PY_CMD = $(PYTHON)
    TEST_CMD = $(PYTEST)
    UVI_CMD = $(UVICORN)
else
    PY_CMD = $(VENV)/bin/python
    TEST_CMD = $(VENV)/bin/pytest
    UVI_CMD = $(VENV)/bin/uvicorn
endif

install:
	$(PY_CMD) -m pip install --upgrade pip
	$(PY_CMD) -m pip install -r requirements.txt

test:
	$(TEST_CMD) backend/tests

bench:
	$(PY_CMD) -m backend.app.bench --compare

demo:
	$(UVI_CMD) backend.app.main:app --reload --port 8000

run: demo

calibrate:
	$(PY_CMD) -m backend.app.calibrate

docker-build:
	docker compose build

docker-up:
	docker compose up -d

clean:
	rm -rf data/*.sqlite bench/*.json .pytest_cache
