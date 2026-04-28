.PHONY: install dev test lint fmt typecheck run docker docker-up docker-down clean

install:
	pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload --port 8000

run:
	gunicorn app.main:app --bind 0.0.0.0:8000 \
		--worker-class uvicorn.workers.UvicornWorker --workers 2

test:
	pytest

lint:
	ruff check app tests

fmt:
	ruff format app tests
	ruff check --fix app tests

typecheck:
	mypy app

docker:
	docker build -t bolna-slack:latest .

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
