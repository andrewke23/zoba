# Zoba Frontend

The web app for **Zoba**, a group trip planner (CSDS 395, Group 2). Members vote on where they
want to go. Zoba combines the votes fairly, builds a day-by-day itinerary, and helps the group
prepare and split costs.

> **The backend isn't built yet.** For now the app runs on a **mock API** inside your browser, so
> every screen works without a server. See [Connecting to the real backend](#connecting-to-the-real-backend).

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

```bash
cd frontend
npm install      # first time, or after pulling new dependencies
npm run dev      # starts the app at http://localhost:5173
```

Open http://localhost:5173 and log in with a demo account below.

| Command | What it does |
|---|---|
| `npm run dev` | Starts the dev server. Saved changes show up instantly. **Use this while working.** |
| `npm run build` | Type-checks and builds the production files into `dist/`. Doesn't start a server. |
| `npm run preview` | Serves the `dist/` build locally, so you can check it. |
| `npm run lint` | Runs ESLint. Please run it before opening a PR. |

---

## Demo accounts

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
    │   ├── index.ts           # Picks mock or real API
    │   ├── http.ts            # Real FastAPI client
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
src/api/index.ts ── VITE_USE_MOCK? ──► mock/   (in-browser, today)
                                  └──► http.ts (FastAPI, later)
```

- Pages **only** talk to the backend through the `api` object. They never call `fetch` directly.
- Both `mock/` and `http.ts` implement the same `ZobaApi` interface in `src/api/types.ts`. Switching between them doesn't change any page code.
- Model field names match the database schema in `data-pipeline/db/schema.sql`.

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

When the FastAPI server is running on port 8000:

```bash
VITE_USE_MOCK=false npm run dev
```

Vite forwards any request to `/api/...` to `http://localhost:8000/...`. You can change the
address with `ZOBA_API_ORIGIN=http://host:port`.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_USE_MOCK` | `true` | `false` = use the real backend |
| `VITE_API_URL` | `/api` | Base URL for API requests |
| `VITE_MAP_STYLE_URL` | OpenFreeMap "liberty" | MapLibre style URL |
| `ZOBA_API_ORIGIN` | `http://localhost:8000` | Where the dev server forwards `/api` |

You can put these in a `frontend/.env.local` file (it's git-ignored).

### Proposed endpoints

These are in `src/api/http.ts`. **They're a proposal. Backend and frontend should agree on them
and keep them in sync.**

| Area | Endpoints |
|---|---|
| Auth (F01) | `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` |
| Trips (F02) | `GET /cities` · `GET, POST /trips` · `GET, PUT /trips/{id}` |
| Invites & members | `GET /invites/{token}` · `POST /invites/{token}/join` · `GET /trips/{id}/members` · `DELETE /trips/{id}/members/{userId}` |
| Preferences (F07a, F08) | `GET /trips/{id}/destinations` · `GET /trips/{id}/preferences/config` · `GET, PUT /trips/{id}/preferences/me` |
| Comparisons (F03, F04) | `GET /trips/{id}/comparisons/me` → `{done, target, next}` · `POST /trips/{id}/comparisons` |
| Ranking (F06, F08a) | `GET /trips/{id}/results` |
| Itinerary (F09–F14) | `GET /trips/{id}/itinerary` · `POST …/itinerary/generate` · `PUT …/itinerary/locks/{destId}` · `POST …/destinations/{destId}/duration` · `POST …/itinerary/compare` |
| Prep (F15–F17) | `/trips/{id}/tasks` · `GET …/costs` · `/expenses` · `GET …/settlement` · `/packing` |

Response formats are the TypeScript types in `src/api/types.ts`.

### Notes for whoever builds the backend

- **Destinations** need `lat`/`lng` (read out of the `geom` column), `hours` (the rows from
  `destination_hours`, as an array), and a `requires_booking` flag. That flag isn't in the
  schema yet; it drives the F15 booking tasks. If `est_duration_min` is NULL, fill in the category default.
- **Itinerary times** should include the city's UTC offset, e.g. `2026-11-06T09:00:00-06:00`.
  The UI shows the `HH:MM` part as-is.
- **Errors**: return JSON `{"detail": "message"}`, as FastAPI does by default. The UI shows `detail` to the user.
  Return 401 when not logged in, and 404 from `GET /itinerary` when none has been generated yet.
- Auth is expected to use **cookies** (`credentials: 'include'`).

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
3. Implement it in `src/api/http.ts`.

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
| Trip size | Max 8 travelers on join | `joinTrip` in `api/mock/index.ts` |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm run build` finished but nothing opened | `build` only creates files. Use `npm run dev`. |
| Map is gray or says it couldn't load | Check your internet connection (tiles are online). The timeline still works. |
| Data looks weird or stuck | Click **Reset demo data** in the yellow banner. |
| Second account can't see the trip | Use a second **tab in the same browser**, not incognito. |
| Changes from another tab don't appear | Navigate to another page or refresh. Tabs don't update live. |
| Logged out after opening a new tab | Expected: each tab has its own login. |
| `command not found: npm` | Install Node.js 20+ from nodejs.org. |
| Port 5173 already in use | Vite picks the next free port. Check the terminal for the URL. |
