# zoba-frontend

React + Vite + TypeScript + Tailwind + MapLibre GL frontend for Zoba (SRS v1.0, §2.3 / §7).
Runs entirely on an in-browser **mock API** until the FastAPI backend exists.

## Quick start

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Demo accounts (password `zoba`): `demo@zoba.app` (organizer of the seeded Chicago trip),
`maya@zoba.app` (member). Invite link for the seeded trip: `/join/chi-fall-26`.
The yellow banner has **Reset demo data**. Mock state lives in `localStorage`.

## Switching to the real backend

```bash
VITE_USE_MOCK=false npm run dev     # /api/* is proxied to http://localhost:8000
```

`src/api/types.ts` defines the `ZobaApi` contract, which both clients implement.
`src/api/http.ts` maps it to REST paths. **Those paths are a proposal**, so agree them with the backend team
and keep the two in sync. Field names already match `data-pipeline/db/schema.sql`.

| Area | Endpoints (proposed) |
|---|---|
| Auth (F01) | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Trips (F02) | `GET/POST /trips`, `GET/PUT /trips/{id}`, `GET /cities` |
| Invites / members | `GET /invites/{token}`, `POST /invites/{token}/join`, `GET /trips/{id}/members`, `DELETE /trips/{id}/members/{uid}` |
| Preferences (F07a, F08) | `GET /trips/{id}/destinations`, `GET /trips/{id}/preferences/config`, `GET/PUT /trips/{id}/preferences/me` |
| Comparisons (F03, F04) | `GET /trips/{id}/comparisons/me` → `{done, target, next}`, `POST /trips/{id}/comparisons` |
| Ranking (F06, F08a) | `GET /trips/{id}/results` |
| Itinerary (F09–F14) | `GET /trips/{id}/itinerary`, `POST …/itinerary/generate {solver}`, `PUT …/itinerary/locks/{destId}`, `POST …/destinations/{destId}/duration`, `POST …/itinerary/compare` |
| Prep (F15–F17) | `/tasks`, `GET /costs`, `/expenses`, `GET /settlement`, `/packing` |

Itinerary timestamps should include the trip city's UTC offset (e.g. `2026-11-06T09:00:00-06:00`).
The UI displays the local `HH:MM` portion as-is.

## Layout

```
src/
  api/
    types.ts         models + ZobaApi contract
    http.ts          FastAPI client
    mock/            in-browser backend: seed data, BT scoring, ranking, scheduler, settlement
  auth/              session context
  components/        ui kit, TripMap (MapLibre), TripForm
  layouts/           app shell, trip layout + nav, TripContext
  pages/             login/register/join/trips/new
  pages/trip/        overview, preferences, compare, results, itinerary, tasks, budget, packing,
                     settings (organizer), solvers (organizer)
```

## Screen ↔ requirement map

| Screen | Requirements |
|---|---|
| Login / Register | F01 |
| New trip, Trip settings | F02, invite link, member management (organizer only) |
| Preferences | F07a (fixed point budget), F08 (hard no), destination discovery |
| This or that | F03, F04 (adaptive pairs, progress toward target count) |
| Group results | F06 (fairness-aware score, worst-off column), F08 (vetoes excluded), F08a (weighted next to raw) |
| Itinerary | F07 (top-pick status), F09, F10, F12 (lock + rebuild), F13 (map + per-day timeline), F14 (duration corrections) |
| Tasks | F15 |
| Costs & expenses | F16, F17 |
| Packing list | §4.1 (no requirement ID yet) |
| Compare solvers | F11, UC-07 |

## Decisions the mock makes for open SRS §8 questions

These are placeholders. Change them once the team decides.

- Point budget **100**, per-place cap **40**, target **15** comparisons (`PREF_CONFIG` in `api/mock/algorithms.ts`).
- Points only, no ranking input. F07a allows either one, and the schema has a `rank` column ready.
- Group score = ½·mean + ½·min of per-member min-max-normalized utilities.
- **Any member may lock** a stop (F12 wording). Only the organizer regenerates. Toggle `MEMBERS_CAN_LOCK`.
- Missing opening hours are treated as open, with a warning.
- Booking tasks are due 7 days before the stop.
