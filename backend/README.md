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
receive the additive `app_user.name` column from the backend at startup.

Users must already exist in `app_user` and have an account in the system that
issues HS256 JWTs using `JWT_SECRET_KEY`. Tokens must contain the user's UUID in
the `sub` claim and an `exp` claim. This backend verifies tokens but does not
register users or issue tokens. Do not expose this signing secret to clients.

## API

All API routes are under `/api/v1` and require a valid bearer token. Trip reads,
expense reads, and expense creation require active trip membership. Only the
organizer can invite an existing user to the trip. The invitee accepts the
pending invitation using their own token. Invitations are recorded in the
database; no email delivery provider is configured. Only the authenticated
payer can record an expense in their name.

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
reboots. Put a TLS reverse proxy (e.g. Caddy or nginx + Let's Encrypt) in
front of port `8000` before serving real traffic.
