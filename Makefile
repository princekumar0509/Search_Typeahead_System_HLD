.PHONY: up down logs seed dataset test backend frontend fmt

# --- Docker -----------------------------------------------------------------
up:            ## Build and start the full stack
	docker compose up --build

down:          ## Stop and remove containers
	docker compose down

logs:          ## Tail backend logs
	docker compose logs -f backend

# --- Local backend ----------------------------------------------------------
dataset:       ## Generate the 120k-row CSV dataset
	cd backend && python -m scripts.generate_dataset --rows 120000

seed:          ## Seed the database (generates CSV if missing)
	cd backend && python -m scripts.seed_database --rows 120000

backend:       ## Run the backend locally (needs Postgres running)
	cd backend && uvicorn app.main:app --reload

test:          ## Run backend tests
	cd backend && pytest -q

# --- Local frontend ---------------------------------------------------------
frontend:      ## Run the frontend dev server
	cd frontend && npm install && npm run dev
