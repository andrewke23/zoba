// FastAPI client for the real backend (app/api), as an adapter: pages keep
// talking to the ZobaApi interface in ./types, and this file translates to and
// from the backend's wire format (see backend/README.md for the contract).
//
// Auth is a bearer JWT kept in sessionStorage (the backend issues tokens on
// register/login; there are no cookies). Only the endpoints the backend
// implements are listed here — src/api/index.ts fills the rest from the mock
// (hybrid mode) or fails them with a 501 (real mode).
import { ApiError } from './types'
import type {
  City,
  CostEstimate,
  Expense,
  ExpenseInput,
  HHMM,
  ISODate,
  ISODateTime,
  Itinerary,
  Member,
  Role,
  SolverMetrics,
  Trip,
  TripInput,
  TripSummary,
  User,
  UUID,
  ZobaApi,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api/v1'

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------

// sessionStorage, like the mock's session: it survives reloads in one tab but
// keeps tabs independent, so two tabs can act as two different travelers.
const TOKEN_KEY = 'zoba_token'

const getToken = () => sessionStorage.getItem(TOKEN_KEY)
const setToken = (token: string) => sessionStorage.setItem(TOKEN_KEY, token)
const clearToken = () => sessionStorage.removeItem(TOKEN_KEY)

// ---------------------------------------------------------------------------
// Request plumbing
// ---------------------------------------------------------------------------

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = data.detail ?? msg
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** Map a specific HTTP status (401 / 404) to null instead of throwing. */
function nullOn<T>(status: number, p: Promise<T>): Promise<T | null> {
  return p.catch((e) => {
    if (e instanceof ApiError && e.status === status) return null
    throw e
  })
}

const t = (tripId: UUID) => `/trips/${tripId}`

// ---------------------------------------------------------------------------
// Backend wire format (app/schemas)
// ---------------------------------------------------------------------------

interface WireUser {
  id: UUID
  email: string
  name: string
  created_at: ISODateTime
}

interface WireAuthToken {
  access_token: string
  token_type: string
  user: WireUser
}

interface WireTrip {
  id: UUID
  organizer_id: UUID
  city_id: string
  name: string
  start_date: ISODate
  end_date: ISODate
  /** "09:00:00" */
  daily_start_time: HHMM
  daily_end_time: HHMM
  home_base_lat: number
  home_base_lon: number
  home_base_label: string
  invite_token: string | null
  created_at: ISODateTime
}

interface WireTripSummary extends WireTrip {
  city_name: string
  my_role: Role
  member_count: number
}

interface WireMember {
  user_id: UUID
  email: string
  display_name: string
  role: Role
  status: Member['status']
}

interface WireInvite {
  trip: WireTrip
  city_name: string
  organizer_name: string
}

interface WireExpense {
  id: UUID
  trip_id: UUID
  payer_id: UUID
  /** "30.00" */
  amount: string
  description: string
  date: ISODateTime
  splits: { debtor_id: UUID; amount_owed: string }[]
}

interface WireSettlement {
  balances: { user_id: UUID; paid_cents: number; owed_cents: number; net_cents: number }[]
  transfers: { from_user: UUID; to_user: UUID; amount: string }[]
}

interface WireCostEstimate {
  trip_id: UUID
  currency: string
  per_person_total: string
  itinerary_stop_count: number
  priced_stop_count: number
  unpriced_stop_count: number
  is_complete: boolean
}

// ---------------------------------------------------------------------------
// Field mapping
// ---------------------------------------------------------------------------

/** Backend Money strings ("10.50") → integer cents. */
const toCents = (amount: string) => Math.round(parseFloat(amount) * 100)
/** Integer cents → backend Money string ("10.50"). */
const fromCents = (cents: number) => (cents / 100).toFixed(2)
/** "09:00:00" → "09:00" for <input type="time"> and formatTime. */
const toHHMM = (value: HHMM) => value.slice(0, 5)

function toUser(wire: WireUser): User {
  return { user_id: wire.id, email: wire.email, display_name: wire.name }
}

function toTrip(wire: WireTrip): Trip {
  return {
    trip_id: wire.id,
    name: wire.name,
    organizer_id: wire.organizer_id,
    city_id: wire.city_id,
    start_date: wire.start_date,
    end_date: wire.end_date,
    day_start: toHHMM(wire.daily_start_time),
    day_end: toHHMM(wire.daily_end_time),
    home_base: { label: wire.home_base_label, lat: wire.home_base_lat, lng: wire.home_base_lon },
    invite_token: wire.invite_token ?? '',
    created_at: wire.created_at,
  }
}

function toTripSummary(wire: WireTripSummary): TripSummary {
  return {
    ...toTrip(wire),
    city_name: wire.city_name,
    my_role: wire.my_role,
    member_count: wire.member_count,
  }
}

function toExpense(wire: WireExpense): Expense {
  return {
    expense_id: wire.id,
    trip_id: wire.trip_id,
    payer_id: wire.payer_id,
    amount_cents: toCents(wire.amount),
    description: wire.description,
    created_at: wire.date,
    shares: wire.splits.map((s) => ({ user_id: s.debtor_id, share_cents: toCents(s.amount_owed) })),
  }
}

/** TripInput (from the trip form) → the backend's create/update payloads. */
function tripBody(input: TripInput) {
  return {
    city_id: input.city_id,
    name: input.name,
    start_date: input.start_date,
    end_date: input.end_date,
    daily_start_time: input.day_start,
    daily_end_time: input.day_end,
    home_base_lat: input.home_base.lat,
    home_base_lon: input.home_base.lng,
    home_base_label: input.home_base.label,
  }
}

async function authSession(email: string, password: string, displayName?: string): Promise<User> {
  const path = displayName === undefined ? '/auth/login' : '/auth/register'
  const body = displayName === undefined ? { email, password } : { email, name: displayName, password }
  const session = await req<WireAuthToken>('POST', path, body)
  setToken(session.access_token)
  return toUser(session.user)
}

async function currentUserId(): Promise<UUID> {
  const me = await realApi.currentUser!()
  if (!me) throw new ApiError(401, 'Please log in.')
  return me.user_id
}

// ---------------------------------------------------------------------------
// Real API (implemented backend endpoints)
// ---------------------------------------------------------------------------

export const realApi: Partial<ZobaApi> = {
  // Auth -------------------------------------------------------------------
  currentUser: () => {
    if (!getToken()) return Promise.resolve(null)
    return nullOn(401, req<WireUser>('GET', '/auth/me').then(toUser))
  },
  register: (email, password, displayName) => authSession(email, password, displayName),
  login: (email, password) => authSession(email, password),
  // Stateless JWT: there is nothing to invalidate server-side, so logout just
  // drops the token. Other tabs keep their own stored token.
  logout: () => {
    clearToken()
    return Promise.resolve()
  },

  // Cities -----------------------------------------------------------------
  listCities: () => req<City[]>('GET', '/cities'),

  // Trips ------------------------------------------------------------------
  listTrips: () => req<WireTripSummary[]>('GET', '/trips').then((trips) => trips.map(toTripSummary)),
  getTrip: (id) => req<WireTrip>('GET', t(id)).then(toTrip),
  createTrip: async (input: TripInput) => {
    const body = { organizer_id: await currentUserId(), ...tripBody(input) }
    return req<WireTrip>('POST', '/trips', body).then(toTrip)
  },
  updateTrip: (id, input: TripInput) => req<WireTrip>('PUT', t(id), tripBody(input)).then(toTrip),

  // Invites & members ------------------------------------------------------
  getInvite: (token) =>
    req<WireInvite>('GET', `/invites/${token}`).then((invite) => ({ ...invite, trip: toTrip(invite.trip) })),
  joinTrip: async (token) => {
    const invite = await req<WireInvite>('GET', `/invites/${token}`)
    await req<WireMember>('POST', `/invites/${token}/join`)
    return toTrip(invite.trip)
  },
  // The backend tracks membership, not voting progress; the flags default to
  // "not submitted" and are overlaid from the mock in hybrid mode.
  listMembers: (id) =>
    req<WireMember[]>('GET', `${t(id)}/members`).then((members) =>
      members.map((m) => ({ ...m, preferences_submitted: false, comparisons_done: 0 })),
    ),
  removeMember: (id, userId) => req<void>('DELETE', `${t(id)}/members/${userId}`),

  // Expenses, settlement, cost estimate ------------------------------------
  listExpenses: (id) => req<WireExpense[]>('GET', `${t(id)}/expenses`).then((items) => items.map(toExpense)),
  addExpense: (id, input: ExpenseInput) => {
    // The backend assigns the payer the unallocated remainder, so the payer's
    // own share is dropped from splits (the form's even split includes it).
    const splits = input.shares
      .filter((share) => share.user_id !== input.payer_id)
      .map((share) => ({ debtor_id: share.user_id, amount_owed: fromCents(share.share_cents) }))
    const body = {
      payer_id: input.payer_id,
      description: input.description,
      amount: fromCents(input.amount_cents),
      date: new Date().toISOString(),
      splits,
    }
    return req<WireExpense>('POST', `${t(id)}/expenses`, body).then(toExpense)
  },
  deleteExpense: (id, expenseId) => req<void>('DELETE', `${t(id)}/expenses/${expenseId}`),
  getSettlement: async (id) => {
    const wire = await req<WireSettlement>('GET', `${t(id)}/settlement`)
    return {
      balances: wire.balances,
      transfers: wire.transfers.map((transfer) => ({
        from_user_id: transfer.from_user,
        to_user_id: transfer.to_user,
        amount_cents: toCents(transfer.amount),
      })),
    }
  },
  // The backend estimates shared admission costs per person (F16); the page's
  // per-traveler table is filled from the member list, with transit and meals
  // reported as not-yet-estimated in the assumptions.
  getCostEstimate: async (id) => {
    const [wire, members] = await Promise.all([
      req<WireCostEstimate>('GET', `${t(id)}/cost-estimate`),
      req<WireMember[]>('GET', `${t(id)}/members`),
    ])
    const perPerson = parseFloat(wire.per_person_total)
    const estimate: CostEstimate = {
      per_member: members
        .filter((m) => m.status === 'joined')
        .map((m) => ({
          user_id: m.user_id,
          admission_usd: perPerson,
          transport_usd: 0,
          meals_usd: 0,
          total_usd: perPerson,
        })),
      assumptions: [
        `Admission for ${wire.priced_stop_count} of ${wire.itinerary_stop_count} planned stops is priced from the destination catalog (${wire.currency}).`,
        ...(wire.unpriced_stop_count > 0
          ? [`${wire.unpriced_stop_count} stop${wire.unpriced_stop_count === 1 ? '' : 's'} without a known admission price ${wire.unpriced_stop_count === 1 ? 'is' : 'are'} excluded.`]
          : []),
        'The same admission estimate applies to every traveler.',
        'Transit and meals are not estimated yet.',
      ],
    }
    return estimate
  },

  // ---- Itinerary (F09-F14) ----
  // The backend returns exactly the Itinerary shape from ./types, so these are
  // passthroughs rather than adapters. Keep them that way: the moment this file
  // starts reshaping the response, the two contracts can drift without anyone
  // noticing, and hybrid mode silently falls back to the mock scheduler.

  // 204 (no itinerary generated yet) becomes null, matching the mock.
  getItinerary: async (id) => (await req<Itinerary | undefined>('GET', `${t(id)}/itinerary`)) ?? null,

  generateItinerary: (id, solver) => req<Itinerary>('POST', `${t(id)}/itinerary`, { solver }),

  // A null lock unpins the stop. Either way the backend re-solves and returns
  // the whole itinerary, so the caller never has to merge state by hand.
  setStopLock: (id, destinationId, lock) =>
    req<Itinerary>('PUT', `${t(id)}/itinerary/stops/${destinationId}/lock`, lock),

  compareSolvers: (id) => req<SolverMetrics[]>('GET', `${t(id)}/itinerary/solver-comparison`),
}

// Domains the backend does not implement yet are intentionally absent from
// realApi; src/api/index.ts fills them (mock in hybrid mode, 501 in real mode):
// preferences, comparisons, group results, tasks, packing.
