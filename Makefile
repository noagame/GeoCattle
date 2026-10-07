.PHONY: configure up down logs demo backup test frontend
configure:
	python3 scripts/configure.py
up: configure
	bash scripts/compose.sh up -d --build
demo:
	bash scripts/compose.sh --profile tools run --rm seed
down:
	bash scripts/compose.sh down
logs:
	bash scripts/compose.sh logs --tail=100 -f api worker
backup:
	bash scripts/backup.sh
test:
	cd backend && uv run pytest
frontend:
	cd frontend && npm ci && npm run build
