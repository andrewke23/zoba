# Zoba
Repo for Zoba group trip planner - senior project

## Backend

The FastAPI backend manages group trips and shared expenses on the same PostGIS
database schema used by `data-pipeline/`. See [backend/README.md](backend/README.md)
for local setup, API contracts, and authentication configuration.

## Frontend

The React app in `frontend/` runs against the backend in **hybrid mode** by
default: accounts, trips, members, invites, expenses, settlement and the cost
estimate are served by the FastAPI backend, while voting, itinerary, tasks and
packing still use the in-browser mock until those backend domains exist. See
[frontend/README.md](frontend/README.md) for setup, API modes, and the demo.

```powershell
docker compose up -d --build   # API + database
cd frontend; npm install; npm run dev   # app at http://localhost:5173
```
