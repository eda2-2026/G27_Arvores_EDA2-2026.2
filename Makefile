# Atalhos do projeto. Use "make help" para ver todos.
PYTHON ?= python3
VENV   ?= .venv
PY      = $(VENV)/bin/python

.PHONY: help install terminal web test docker clean

help:            ## Lista os comandos disponíveis
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install:         ## Cria o ambiente virtual e instala o Flask
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -r requirements.txt

terminal:        ## Abre o MiniFS no terminal (não precisa de dependências)
	$(PYTHON) -m minifs

web: install     ## Sobe a interface web em http://127.0.0.1:5000
	$(PY) -m minifs.web

test: install    ## Roda todos os testes
	$(PY) -m unittest discover -v

docker:          ## Sobe a interface web via Docker em http://localhost:5000
	docker build -t minifs .
	docker run --rm -p 5000:5000 minifs

clean:           ## Remove ambiente virtual e caches
	rm -rf $(VENV) **/__pycache__
