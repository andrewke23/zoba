# Zoba backend

FastAPI trip and expense APIs that use the shared PostGIS schema in
`data-pipeline/db/schema.sql`. The backend maps the existing `app_user`, `trip`,
`membership`, `expense`, and `expense_share` tables; trip expenses are stored as
integer cents to match the data layer and avoid floating-point currency errors.

## Local setup

From the repository root:

```powershell
Copy-Item .env.example .env
# Replace POSTGRES_PASSWORD, DATABASE_URL, and JWT_SECRET_KEY with matching,
# strong values. URL-encode any reserved characters in DATABASE_URL's password.
docker compose up --build
```

The API is available at `http://localhost:8000`, with OpenAPI docs at
`http://localhost:8000/docs`. PostgreSQL is bound to localhost. The database
initializer applies the shared schema only for a new volume; existing databases
receive additive columns from the backend at startup (`app_user.name`,
`trip.name`, `trip.home_base_label`, and invite tokens for older trips).

Browser origins allowed to call the API directly are set with `CORS_ORIGINS`
(comma-separated; defaults to the Vite dev and preview origins). The frontend
dev server proxies `/api` same-origin, so CORS only matters when the UI is
served from a different origin.
receive the additive `app_user.name` column from the backend at startup.

Anyone can create an account with `POST /auth/register`; passwords are hashed
with bcrypt (cost 12) and never stored or logged in plain text. Login responses
are identical for unknown emails and wrong passwords, so they cannot be used to
probe which addresses are registered. Existing `app_user` rows seeded by the
data pipeline can log in only if their `password_hash` is a bcrypt hash; rows
with placeholder hashes always fail authentication.

The backend issues and verifies its own HS256 JWTs signed with `JWT_SECRET_KEY`.
Tokens carry the user's UUID in the `sub` claim plus `iat`/`exp` and expire
after `ACCESS_TOKEN_TTL_MINUTES` (default 24 hours). Do not expose this signing
secret to clients.

## API

All API routes are under `/api/v1` and require a valid bearer token, except
registration, login, invite previews, and the health check. Trip reads, expense
reads, and expense creation require active trip membership. Only the organizer
can invite an existing user to the trip, edit the trip, or remove members.
Invitations are recorded in the database; no email delivery provider is
configured. Only the authenticated payer can record or delete an expense in
registration, login, and the health check. Trip reads, expense reads, and
expense creation require active trip membership. Only the organizer can invite
an existing user to the trip. The invitee accepts the pending invitation using
their own token. Invitations are recorded in the database; no email delivery
provider is configured. Only the authenticated payer can record an expense in
their name.

* `POST /auth/register`: Create a user (`email`, `name`, `password` of at
  least 8 characters and at most 72 bytes) and return a bearer token. Duplicate
  emails return 409; emails are stored lowercased.
* `POST /auth/login`: Authenticate with `email` and `password`, returning a
  bearer token. Wrong credentials return 401.
* `GET /auth/me`: Return the authenticated user's profile.
* `GET /cities`: List pipeline cities with a `[lng, lat]` centroid of each
  bounding box and the IANA timezone, for the trip form's city picker.
* `POST /trips`: Create a trip (`name`, `city_id`, dates, daily window, home
  base label and coordinates). `organizer_id` must match the JWT subject, and
  `city_id` must refer to an existing pipeline city. Returns the trip with its
  generated invite token.
* `GET /trips`: List the trips the caller has joined, newest first, each with
  the city name, the caller's role, and the joined-member count.
* `GET /trips/{trip_id}`: Read trip details, home-base coordinates and label,
  and invite token (members only).
* `PUT /trips/{trip_id}`: Update trip settings (organizer only). Omitted fields
  keep their current values.
* `GET /invites/{token}`: Preview an invite trip, city and organizer names.
  Unauthenticated so the join page can render before sign-in; the unguessable
  token is the authorization.
* `POST /invites/{token}/join`: Join the trip behind an invite link as a
  member. Idempotent for existing members; returns 409 when the trip already
  has 8 joined travelers.
* `GET /trips/{trip_id}/members`: List members (members only) with email,
  display name, role, and invitation status.
* `POST /trips/{trip_id}/members`: Add an existing user by `user_id` (organizer
  only). Creates a pending invitation; returns 409 when the trip is full.
* `POST /trips/{trip_id}/members/accept`: Accept the current user's pending
  invitation.
* `DELETE /trips/{trip_id}/members/{user_id}`: Remove a member (organizer
  only). The organizer cannot be removed.
* `POST /trips`: Create a trip. `organizer_id` must match the JWT subject, and
  `city_id` must refer to an existing pipeline city.
* `GET /trips/{trip_id}`: Read trip details and home-base coordinates.
* `POST /trips/{trip_id}/members`: Add an existing user by `user_id` (organizer
  only). Creates a pending invitation.
* `POST /trips/{trip_id}/members/accept`: Accept the current user's pending
  invitation.
* `POST /trips/{trip_id}/expenses`: Record the payer, description, amount,
  timestamp, and debtor shares. Shares omit the payer; the payer is assigned
  the remaining amount. Shares cannot exceed the expense total.
* `GET /trips/{trip_id}/expenses`: Read the trip ledger.
* `DELETE /trips/{trip_id}/expenses/{expense_id}`: Delete an expense (the
  authenticated payer only).
* `GET /trips/{trip_id}/settlement`: Return per-member balances (`paid_cents`,
  `owed_cents`, `net_cents`) plus the list of minimum greedy transfers with
  `from_user`, `to_user`, and `amount`.
* `GET /trips/{trip_id}/settlement`: Return a list of minimum greedy transfers
  with `from_user`, `to_user`, and `amount`.
* `GET /trips/{trip_id}/cost-estimate`: Sum known destination admission prices
  across the itinerary for one person, reporting priced/unpriced stop counts
  and whether the estimate is complete.
* `GET /healthz`: Check database connectivity.

The F16 estimate covers admission costs only; unknown destination prices are
excluded from the subtotal and reported, not treated as zero-cost attractions.
It does not estimate meals, lodging, transport, or shared expenses. Money is
USD with two decimal places. Settlement nets payments against expense shares
and returns deterministic transfers.

## Tests

```powershell
Set-Location backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

With the compose stack running, the end-to-end smoke test seeds a city, users,
and a priced destination, then exercises the whole documented API flow with
real JWTs (trip creation, invites, expenses, settlement, cost estimate, and
auth edge cases):

```powershell
python tests\e2e_smoke.py
```

## Deployment (AWS EC2)

The services are stateless and configured entirely through environment
variables, so an EC2 instance only needs Docker installed:

```bash
git clone <repo> && cd zoba
cp .env.example .env      # set strong POSTGRES_PASSWORD, DATABASE_URL, JWT_SECRET_KEY
docker compose up -d --build
```

The backend publishes port `8000` on all interfaces and the database stays
bound to `127.0.0.1`. Open inbound TCP `8000` in the EC2 security group and
keep `5432` closed. Both services use `restart: unless-stopped` to survive
reboots. When the frontend is served from another origin, set `CORS_ORIGINS`
to its URL. Put a TLS reverse proxy (e.g. Caddy or nginx + Let's Encrypt) in
reboots. Put a TLS reverse proxy (e.g. Caddy or nginx + Let's Encrypt) in
front of port `8000` before serving real traffic.

## Input embeddings

Trip creation and expense entry also write a 64-dimension vector of the
member's input to `input_embedding` (`app/services/embedder.py`) in the same
transaction, for later analysis such as clustering members or finding similar
trips. Vectors come from a deterministic feature-hashing projection, so no
model download or external API is involved. Each row stores `input_kind`,
`source_id` (the embedded row's key) and `embedder_version`, not the raw input.
`preference_features` and `comparison_features` are ready for the preference
and pairwise-comparison endpoints once they exist.
