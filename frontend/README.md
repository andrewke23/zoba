# Zoba Frontend

The web app for **Zoba**, a group trip planner (CSDS 395, Group 2). Members vote on where they
want to go. Zoba combines the votes fairly, builds a day-by-day itinerary, and helps the group
prepare and split costs.

> The app runs in **hybrid mode** by default: accounts, trips, members, expenses, settlement and the
> cost estimate talk to the real FastAPI backend, while voting, itinerary, tasks and packing still use
> an in-browser **mock API** until their backend domains exist. Set `VITE_API_MODE=mock` for the pure
> demo (no server needed) or `VITE_API_MODE=real` to require the backend everywhere. See
> [Connecting to the real backend](#connecting-to-the-real-backend).

---

## Contents

- [Quick start](#quick-start)
- [Demo accounts](#demo-accounts)
- [Testing with multiple users](#testing-with-multiple-users)
- [What's in the app](#whats-in-the-app)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [How data flows](#how-data-flows)
- [Connecting to the real backend](#connecting-to-the-real-backend)
- [Common tasks](#common-tasks)
- [Placeholder decisions](#placeholder-decisions)
- [Troubleshooting](#troubleshooting)

---

## Quick start

You need **Node.js 20+** (`node -v` to check).

Start the backend first (from the repository root — see [backend/README.md](../backend/README.md)):

```powershell
docker compose up -d --build   # API on http://localhost:8000, needs a configured .env
```

Then, in `frontend/`:

```bash
npm install      # first time, or after pulling new dependencies
npm run dev      # starts the app at http://localhost:5173
```

Open http://localhost:5173, register an account, and you're in. To try the full demo without any
server, run `VITE_API_MODE=mock npm run dev` instead and log in with a demo account below.

| Command | What it does |
|---|---|
| `npm run dev` | Starts the dev server. Saved changes show up instantly. **Use this while working.** |
| `npm run build` | Type-checks and builds the production files into `dist/`. Doesn't start a server. |
| `npm run preview` | Serves the `dist/` build locally, so you can check it. |
| `npm run lint` | Runs ESLint. Please run it before opening a PR. |
| `npm run smoke` | With the backend + dev server running, checks every real API call through the proxy. |

---

## Demo accounts

> Demo accounts only exist in **mock mode** (`VITE_API_MODE=mock`). In hybrid and real modes,
> accounts live on the backend — register your own.

All demo accounts use the password **`zoba`**. The login page has buttons that fill these in.

| Email | Role in the "Chicago Fall Weekend" trip |
|---|---|
| `demo@zoba.app` | **Organizer**: sees everything, including Trip settings, Generate itinerary, and Compare solvers |
| `maya@zoba.app` | **Member**: has already voted (likes art and architecture, vetoed Wrigley Field) |
| `jordan@zoba.app` | **Member**: has already voted (likes sports, pizza, viewpoints) |
| `sam@zoba.app` | **Member**: has already voted (likes museums and the aquarium, vetoed the Green Mill) |

The demo organizer **hasn't voted yet**, so you can try the voting flow from the start.

You can also register any new email, then join the seeded trip with the invite link:
**http://localhost:5173/join/chi-fall-26**

To start over, click **Reset demo data** in the yellow banner at the top of the page.

---

## Testing with multiple users

Each browser **tab** can be logged in as a different person, and all tabs share the same trip data.

1. Tab 1: log in as `demo@zoba.app`.
2. Tab 2 (same browser): log in as `maya@zoba.app`.
3. Make a change in one tab. In the other tab, **click to another page or refresh** to see it. Tabs don't update live.

⚠️ **Don't use a private/incognito window for the second user.** It has its own separate storage,
so it won't see the other tab's data.

Things to try:
- Maya marks a place as a hard no → the organizer regenerates the itinerary → the place disappears from the plan.
- Maya locks a stop → the organizer sees it marked 🔒.
- One person adds an expense → the other sees the "Settle up" amounts change.

---

## What's in the app

The typical flow, from the SRS (§2.2):

**Create trip → invite → allocate points → this-or-that voting → group ranking → generate itinerary → map/timeline → tasks & costs → split expenses**

| Page | What it does | SRS |
|---|---|---|
| **Login / Register** | Email + password accounts | F01 |
| **My trips** | Lists your trips; create a new one | — |
| **New trip / Trip settings** *(organizer)* | City, dates, daily start/end times, home base (click the map), invite link, remove members | F02 |
| **Overview** | Your next steps + everyone's voting progress | — |
| **Preferences** | Spend 100 points across places; mark "hard no" vetoes | F07a, F08 |
| **This or that** | Pick between two places; the next pair is the most useful one to ask about | F03, F04 |
| **Group results** | Fairness-aware ranking, weighted scores next to raw votes, vetoed places listed separately | F06, F08, F08a |
| **Itinerary** | Map + per-day timeline, lock a stop to a day/time, fix visit lengths, see if everyone's top pick made it | F07, F09–F14 |
| **Tasks** | Booking reminders created from the itinerary, plus your own tasks | F15 |
| **Costs & expenses** | Estimated cost per person, shared expense ledger, "who pays whom" settlement | F16, F17 |
| **Packing list** | Items everyone brings + shared items assigned to one person | §4.1 |
| **Compare solvers** *(organizer)* | Runs the fast and the optimized scheduler on the same inputs and compares them | F11, UC-07 |

Every page works on phones. On narrow screens the side menu becomes a scrollable tab bar.

---

## Tech stack

| Tool | Used for | Docs |
|---|---|---|
| [React 19](https://react.dev) + TypeScript | UI components, type safety | react.dev/learn |
| [Vite](https://vite.dev) | Dev server + build | vite.dev/guide |
| [React Router 7](https://reactrouter.com) | Page routing (`src/App.tsx`) | reactrouter.com |
| [Tailwind CSS 4](https://tailwindcss.com) | Styling with utility classes | tailwindcss.com/docs |
| [MapLibre GL](https://maplibre.org) | Interactive maps | maplibre.org/maplibre-gl-js/docs |

Map tiles come from [OpenFreeMap](https://openfreemap.org). They're free and need no API key, but they do need an internet connection.

There's no component library and no data-fetching library. Shared UI pieces are in
`src/components/ui.tsx`, and data loading uses a small `useAsync` hook.

---

## Project structure

```
frontend/
├── index.html
├── vite.config.ts             # Tailwind plugin, /api proxy, build settings
└── src/
    ├── main.tsx               # App entry point
    ├── App.tsx                # All routes (URLs → pages)
    ├── index.css              # Tailwind + brand colors
    │
    ├── api/
    │   ├── types.ts           # ⭐ Data models + the ZobaApi interface (start here)
    │   ├── index.ts           # Picks the API mode: mock / hybrid / real
    │   ├── http.ts            # Real FastAPI client (translates to the backend wire format)
    │   └── mock/
    │       ├── seed.ts        # Demo users, trip, Chicago places, expenses
    │       ├── db.ts          # In-browser "database" (localStorage)
    │       ├── algorithms.ts  # Stand-in scoring, ranking, scheduling, settlement
    │       └── index.ts       # Mock version of every API call
    │
    ├── auth/AuthContext.tsx   # Who's logged in (useAuth)
    ├── hooks/useAsync.ts      # useAsync (load data) + useAction (submit changes)
    ├── lib/                   # Formatting helpers (dates, money, categories) + cx()
    ├── components/
    │   ├── ui.tsx             # Button, Card, Badge, Modal, Input, …
    │   ├── TripMap.tsx        # Itinerary map
    │   └── TripForm.tsx       # Create/edit trip form
    ├── layouts/
    │   ├── AppShell.tsx       # Top header + demo banner
    │   ├── AuthLayout.tsx     # Login/register page frame
    │   ├── TripLayout.tsx     # Trip nav (sidebar / mobile tabs)
    │   └── TripContext.ts     # useTrip(): current trip, members, isOrganizer
    └── pages/
        ├── LoginPage, RegisterPage, JoinPage, TripsPage, NewTripPage
        └── trip/              # One file per trip page (see table above)
```

---

## How data flows

```
Page component
   │  api.listTasks(tripId)
   ▼
src/api/index.ts ── VITE_API_MODE ──► mock/             (mock: everything)
                          │
                          ├────────► http.ts → backend  (hybrid: real where built,
                          │                        mock for voting/itinerary/tasks/packing)
                          └────────► http.ts only       (real: 501 for anything unbuilt)
```

- Pages **only** talk to the backend through the `api` object. They never call `fetch` directly.
- Both `mock/` and `http.ts` implement the same `ZobaApi` interface in `src/api/types.ts`, so pages
  don't care which one is active. `http.ts` also translates between the frontend models and the
  backend's wire format (field names, money as cents vs decimal strings, …).

A typical page looks like this:

```tsx
const { trip } = useTrip()                                        // current trip
const { data, error, reload } = useAsync(() => api.listTasks(trip.trip_id), [trip.trip_id])
const add = useAction(async (title: string) => { await api.addTask(trip.trip_id, title, null); await reload() })

if (error) return <ErrorBox error={error} onRetry={reload} />
if (!data) return <Loading />
```

---

## Connecting to the real backend

The app picks its API implementation from `VITE_API_MODE`:

| Mode | Behavior |
|---|---|
| `hybrid` (default) | Real backend where it exists, in-browser mock elsewhere. The yellow banner says which parts are live. |
| `mock` | Pure demo — everything is mocked, no server needed. |
| `real` | Everything must be real; calls the backend doesn't implement fail with a clear 501. Use this to see what's still missing. |

The dev server forwards any request under `/api/...` to the FastAPI server (default
`http://localhost:8000`; override with `ZOBA_API_ORIGIN=http://host:port`). The backend already
serves `/api/v1/*`, so nothing is rewritten.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_MODE` | `hybrid` | `mock` \| `hybrid` \| `real` (see table above) |
| `VITE_USE_MOCK` | — | Legacy: `true` is the same as `VITE_API_MODE=mock` |
| `VITE_API_URL` | `/api/v1` | Base URL for API requests |
| `VITE_MAP_STYLE_URL` | OpenFreeMap "liberty" | MapLibre style URL |
| `ZOBA_API_ORIGIN` | `http://localhost:8000` | Where the dev server forwards `/api` |

You can put these in a `frontend/.env.local` file (it's git-ignored); see `.env.example`.

### Auth

The backend issues a **bearer JWT** on register/login; `src/api/http.ts` keeps it in
`sessionStorage` (per tab, like the mock's session — so two tabs can act as two travelers) and
sends `Authorization: Bearer …` with every request. There are no cookies, so cross-origin use
needs the backend's `CORS_ORIGINS` to include the frontend origin.

### What's real vs. mock today

| Real (FastAPI) | Still mock |
|---|---|
| Register / login / me | Preferences & point allocation (F07a, F08) |
| Trip create / read / update / list | This-or-that comparisons (F03, F04) |
| Cities catalog | Group results & fairness ranking (F06, F08a) |
| Invite links, join, member list & removal | Itinerary generation, locks, solver comparison (F09–F14) |
| Expenses (add / list / delete) | Tasks (F15) |
| Settlement (balances + transfers) | Packing list |
| Cost estimate (admissions, F16) | |

When the backend adds an endpoint, implement it in `src/api/http.ts` and move the method from the
mock to the real side in `src/api/index.ts`.

### Verifying the wiring

With the compose stack and `npm run dev` running:

```bash
npm run smoke
```

`scripts/proxy-smoke.mjs` drives every real API call through the dev proxy with the same payloads
`http.ts` sends, and checks the responses.

### Notes for the remaining backend domains

- **Destinations** need `lat`/`lng` (read out of the `geom` column), `hours` (the rows from
  `destination_hours`, as an array), and a `requires_booking` flag. That flag isn't in the
  schema yet; it drives the F15 booking tasks. If `est_duration_min` is NULL, fill in the category default.
- **Itinerary times** should include the city's UTC offset, e.g. `2026-11-06T09:00:00-06:00`.
  The UI shows the `HH:MM` part as-is.
- **Errors**: return JSON `{"detail": "message"}`, as FastAPI does by default. The UI shows `detail` to the user.
  Return 401 when not logged in, and 404 from `GET /itinerary` when none has been generated yet.
- Voting progress on the members payload (`preferences_submitted`, `comparisons_done`) is overlaid
  from the mock in hybrid mode; drop that overlay in `src/api/index.ts` once the backend computes it.

---

## Common tasks

### Add a new page to a trip

1. Create `src/pages/trip/MyPage.tsx` (copy a small one, like `PackingPage.tsx`).
2. Add a route in `src/App.tsx` inside the `/trips/:tripId` route:
   `<Route path="my-page" element={<MyPage />} />`
3. Add a menu item to `NAV` in `src/layouts/TripLayout.tsx`. Set `organizerOnly: true` if only organizers should see it.

### Add a new API call

1. Add the method to the `ZobaApi` interface in `src/api/types.ts`.
2. Implement it in `src/api/mock/index.ts` (TypeScript will complain until you do).
3. Implement it in `src/api/http.ts` when the backend endpoint exists, and move the method from
   the mock to the real side of the dispatch in `src/api/index.ts`.

### Change the demo data

Edit `src/api/mock/seed.ts`, then click **Reset demo data** in the yellow banner, or bump
`VERSION` in `src/api/mock/db.ts`. Saved browser data from the old version is ignored after a bump.

### Styling

Use Tailwind classes directly on elements. The brand colors are `brand-50` … `brand-900` (teal) and
`accent-500/600` (orange), defined in `src/index.css`. Reuse components from `components/ui.tsx`
before writing new ones.

---

## Placeholder decisions

SRS §8 leaves these questions open. The mock picks a value for each so the app works. **Change them once the team decides.**

| Question | Current choice | Where to change it |
|---|---|---|
| Point budget / per-place cap | 100 points, cap 40 | `PREF_CONFIG` in `api/mock/algorithms.ts` |
| Minimum comparisons | 15 | `PREF_CONFIG` |
| Ranking input vs. points | Points only (schema has `rank` ready) | `PreferencesPage.tsx` |
| Fairness objective | ½ × average + ½ × least-happy member | `computeRanking` in `algorithms.ts` |
| Who can lock stops | Any member (only the organizer regenerates) | `MEMBERS_CAN_LOCK` in `api/mock/index.ts` |
| Missing opening hours | Treated as open, with a warning | `algorithms.ts` |
| Booking task due date | 7 days before the stop | `syncAutoTasks` in `api/mock/index.ts` |
| Trip size | Max 8 travelers on join | `joinTrip` in `api/mock/index.ts` and `MAX_TRIP_MEMBERS` in `backend/app/api/dependencies.py` |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm run build` finished but nothing opened | `build` only creates files. Use `npm run dev`. |
| Login/register fails with a network error | The backend isn't running. `docker compose up -d --build`, or run demo mode: `VITE_API_MODE=mock npm run dev`. |
| Map is gray or says it couldn't load | Check your internet connection (tiles are online). The timeline still works. |
| Data looks weird or stuck | Click **Reset demo data** in the yellow banner (mock data only). |
| Second account can't see the trip | Use a second **tab in the same browser**, not incognito. |
| Changes from another tab don't appear | Navigate to another page or refresh. Tabs don't update live. |
| Logged out after opening a new tab | Expected: each tab has its own login. |
| `command not found: npm` | Install Node.js 20+ from nodejs.org. |
| Port 5173 already in use | Vite picks the next free port. Check the terminal for the URL. |
