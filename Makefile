# OrbitGuard - make data | train | eval | api | web | test
# On Windows without make, use the equivalent:  .\make.ps1 <target>
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
else
PY ?= .venv/bin/python
endif

.PHONY: setup data mocks train eval demo api web test

setup:
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt
	cd web && npm install

data:
	$(PY) -m orbitguard.download

mocks:
	$(PY) -m api.mock.generate_mocks

train:
	$(PY) -m orbitguard.features
	$(PY) -m orbitguard.models

eval:
	$(PY) -m orbitguard.evaluate
	$(PY) -m orbitguard.pc

demo:
	$(PY) -m orbitguard.build_demo

api:
	$(PY) -m uvicorn api.main:app --reload --port 8000

web:
	cd web && npm run dev

test:
	$(PY) -m pytest -q
