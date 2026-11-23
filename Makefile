.DEFAULT_GOAL := help
PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(PY) -m pip
SQL ?= custom.sql
BACKUP ?=
EXPORT ?=
COMPOSE := docker compose --env-file .env -f compose.yaml

.PHONY: help venv env install install-dev compile init setup run serve user reset-password import-sql import-check backup test check lint format docker-build docker-up docker-down docker-logs docker-init docker-user docker-import docker-import-check
.PHONY: export-sql

help: ## 📖 Mostrar todos los comandos disponibles y su descripción
	@echo ''
	@echo '🏠 Homeio · Comandos disponibles'
	@echo ''
	@echo '  make help                   📖 Mostrar todos los comandos disponibles y su descripción'
	@echo '  make venv                   🐍 Crear el entorno virtual de Python (.venv)'
	@echo '  make env                    🔑 Preparar .env y data/ conservando la configuración existente'
	@echo '  make install                📦 Instalar las dependencias de la aplicación en el entorno virtual'
	@echo '  make install-dev            🛠️ Instalar las dependencias de la aplicación y las herramientas de desarrollo'
	@echo '  make compile                📌 Actualizar los archivos requirements.txt y requirements-dev.txt desde los .in'
	@echo '  make init                   🗃️ Inicializar SQLite sin borrar datos (requiere make install)'
	@echo '  make setup                  🚀 Instalar dependencias, preparar .env e inicializar SQLite'
	@echo '  make run                    ▶️ Iniciar el servidor local de desarrollo (HOMEIO_HOST y HOMEIO_PORT)'
	@echo '  make serve                  🌐 Iniciar Gunicorn en 127.0.0.1:8000 con dos procesos'
	@echo '  make user                   👤 Crear un usuario de forma interactiva en la base compartida'
	@echo '  make reset-password         🔐 Cambiar una contraseña y cerrar todas las sesiones de ese usuario'
	@echo '  make import-check           🔎 Validar el SQL sin guardar cambios (SQL=ruta.sql)'
	@echo '  make import-sql             📥 Importar SQL en un libro vacío (SQL=ruta.sql)'
	@echo '  make backup                 💾 Crear una copia en HOMEIO_BACKUP (destino opcional: BACKUP=ruta/copia.sqlite3)'
	@echo '  make export-sql             📤 Volcar esquema y datos a SQL en HOMEIO_BACKUP (EXPORT=ruta/volcado.sql)'
	@echo '  make test                   🧪 Ejecutar las pruebas de dominio, persistencia, importación y seguridad HTTP'
	@echo '  make check                  ✅ Ejecutar las pruebas y comprobar la sintaxis de Python'
	@echo '  make lint                   🔍 Revisar el código con Ruff (requiere make install-dev)'
	@echo '  make format                 ✨ Formatear el código Python con Ruff (requiere make install-dev)'
	@echo '  make docker-build           🏗️ Construir la imagen Docker con alternativa si Buildx no está disponible'
	@echo '  make docker-up              🐳 Preparar el entorno, construir la imagen e iniciar Docker en segundo plano'
	@echo '  make docker-down            ⏹️ Detener y eliminar los contenedores conservando los datos de ./data'
	@echo '  make docker-logs            📋 Seguir los registros de la aplicación en Docker'
	@echo '  make docker-init            🗃️ Inicializar la base compartida mediante Docker sin iniciar la web'
	@echo '  make docker-user            👤 Crear un usuario en la base compartida desde el contenedor en ejecución'
	@echo '  make docker-import-check    🔎 Validar SQL mediante Docker sin guardar cambios (SQL=ruta.sql)'
	@echo '  make docker-import          📥 Importar SQL mediante Docker en un libro vacío (SQL=ruta.sql)'
	@echo ''
	@echo 'Ejemplo: make import-check SQL=ruta.sql'
	@echo ''

venv: ## 🐍 Crear el entorno virtual de Python (.venv)
	$(PYTHON) -m venv $(VENV)

env: ## 🔑 Preparar .env y data/ conservando la configuración existente
	$(PYTHON) scripts/configure.py

$(PY):
	$(PYTHON) -m venv $(VENV)

install: $(PY) ## 📦 Instalar las dependencias de la aplicación en el entorno virtual
	$(PIP) install -r requirements.txt

install-dev: install ## 🛠️ Instalar las dependencias de la aplicación y las herramientas de desarrollo
	$(PIP) install -r requirements-dev.txt

compile: $(PY) ## 📌 Actualizar los archivos requirements.txt y requirements-dev.txt desde los .in
	$(PIP) install 'pip==25.0.1' 'pip-tools==7.5.2' 'click==8.1.8'
	$(VENV)/bin/pip-compile --allow-unsafe --resolver=backtracking --strip-extras --output-file=requirements.txt requirements.in
	$(VENV)/bin/pip-compile --allow-unsafe --resolver=backtracking --strip-extras --output-file=requirements-dev.txt requirements-dev.in

init: env ## 🗃️ Inicializar SQLite sin borrar datos (requiere make install)
	$(PY) -m homeio.cli init

setup: install ## 🚀 Instalar dependencias, preparar .env e inicializar SQLite
	$(MAKE) init

run: ## ▶️ Iniciar el servidor local de desarrollo (HOMEIO_HOST y HOMEIO_PORT)
	$(PY) -m homeio.cli serve

serve: ## 🌐 Iniciar Gunicorn en 127.0.0.1:8000 con dos procesos
	$(VENV)/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 30 'homeio.web.app:create_app()'

user: ## 👤 Crear un usuario de forma interactiva en la base compartida
	$(PY) -m homeio.cli user

reset-password: ## 🔐 Cambiar una contraseña y cerrar todas las sesiones de ese usuario
	$(PY) -m homeio.cli user --reset-password

import-check: ## 🔎 Validar el SQL sin guardar cambios (SQL=ruta.sql)
	$(PY) -m homeio.cli import-sql "$(SQL)" --dry-run

import-sql: ## 📥 Importar SQL en un libro vacío (SQL=ruta.sql)
	$(PY) -m homeio.cli import-sql "$(SQL)"

backup: ## 💾 Crear una copia en HOMEIO_BACKUP (destino opcional: BACKUP=ruta/copia.sqlite3)
	$(PY) -m homeio.cli backup $(if $(BACKUP),"$(BACKUP)")

export-sql: ## 📤 Volcar esquema y datos a SQL en HOMEIO_BACKUP (EXPORT=ruta/volcado.sql)
	$(PY) -m homeio.cli export-sql $(if $(EXPORT),"$(EXPORT)")

test: ## 🧪 Ejecutar las pruebas de dominio, persistencia, importación y seguridad HTTP
	$(PY) -m unittest discover -s tests -v

check: test ## ✅ Ejecutar las pruebas y comprobar la sintaxis de Python
	$(PY) -m compileall -q homeio scripts tests

lint: ## 🔍 Revisar el código con Ruff (requiere make install-dev)
	$(VENV)/bin/ruff check .

format: ## ✨ Formatear el código Python con Ruff (requiere make install-dev)
	$(VENV)/bin/ruff format .

docker-build: ## 🏗️ Construir la imagen Docker con alternativa si Buildx no está disponible
	$(COMPOSE) build || DOCKER_BUILDKIT=0 $(COMPOSE) build

docker-up: env ## 🐳 Preparar el entorno, construir la imagen e iniciar Docker en segundo plano
	$(MAKE) docker-build
	$(COMPOSE) up -d --no-build

docker-down: ## ⏹️ Detener y eliminar los contenedores conservando los datos de ./data
	$(COMPOSE) down

docker-logs: ## 📋 Seguir los registros de la aplicación en Docker
	$(COMPOSE) logs -f app

docker-init: env ## 🗃️ Inicializar la base compartida mediante Docker sin iniciar la web
	$(COMPOSE) run --rm app python -m homeio.cli init

docker-user: ## 👤 Crear un usuario en la base compartida desde el contenedor en ejecución
	$(COMPOSE) exec app python -m homeio.cli user

docker-import-check: ## 🔎 Validar SQL mediante Docker sin guardar cambios (SQL=ruta.sql)
	$(COMPOSE) run --rm -v "$(abspath $(SQL)):/import/backup.sql:ro" app python -m homeio.cli import-sql /import/backup.sql --dry-run

docker-import: ## 📥 Importar SQL mediante Docker en un libro vacío (SQL=ruta.sql)
	$(COMPOSE) run --rm -v "$(abspath $(SQL)):/import/backup.sql:ro" app python -m homeio.cli import-sql /import/backup.sql
