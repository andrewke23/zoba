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
  ComparisonProgress,
  CostEstimate,
  Destination,
  Expense,
  ExpenseInput,
  GroupResults,
  HHMM,
  ISODate,
  ISODateTime,
  Itinerary,
  Member,
  PackingItem,
  Preference,
  PreferenceConfig,
  Role,
  RouteLeg,
  SolverMetrics,
  Task,
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
      msg = formatDetail(data.detail) ?? msg
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/**
 * FastAPI's `detail` is a string for HTTPException, but a list of
 * `{loc, msg}` objects for 422 validation errors. Flatten either to text.
 */
function formatDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (!d || typeof d !== 'object') return String(d)
      const { loc, msg } = d as { loc?: unknown[]; msg?: string }
      const field = Array.isArray(loc) ? loc.filter((p) => p !== 'body').join('.') : ''
      const text = (msg ?? 'Invalid value').replace(/^Value error, /, '')
      return field ? `${field}: ${text}` : text
    })
    return parts.length ? parts.join('; ') : undefined
  }
  return undefined
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
  transport_per_person: string
  transit_leg_count: number
  taxi_leg_count: number
  transit_fare: string
  taxi_fare_per_person: string
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
  // Each member comes with their voting progress (preferences submitted,
  // comparisons done), so the overview and preferences pages read it directly.
  listMembers: (id) => req<Member[]>('GET', `${t(id)}/members`),
  removeMember: (id, userId) => req<void>('DELETE', `${t(id)}/members/${userId}`),

  // Destinations ------------------------------------------------------------
  // The backend returns the Destination shape from ./types as-is.
  listDestinations: (id) => req<Destination[]>('GET', `${t(id)}/destinations`),

  // Preferences, comparisons, group results ---------------------------------
  // The backend returns the shapes from ./types as-is.
  getPreferenceConfig: (id) => req<PreferenceConfig>('GET', `${t(id)}/preference-config`),
  getMyPreferences: (id) => req<Preference[]>('GET', `${t(id)}/preferences/me`),
  saveMyPreferences: (id, prefs) => req<void>('PUT', `${t(id)}/preferences/me`, prefs),
  getComparisonProgress: (id) => req<ComparisonProgress>('GET', `${t(id)}/comparisons/progress`),
  submitComparison: (id, pair, chosen) =>
    req<ComparisonProgress>('POST', `${t(id)}/comparisons`, { ...pair, chosen }),
  undoLastComparison: (id) => req<ComparisonProgress>('DELETE', `${t(id)}/comparisons/last`),
  getGroupResults: (id) => req<GroupResults>('GET', `${t(id)}/group-results`),

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
  // The backend estimates shared admission and transport (transit/taxi fares
  // from the itinerary's legs) per person (F16); the page's per-traveler table
  // is filled from the member list. Meals are not estimated yet.
  getCostEstimate: async (id) => {
    const [wire, members] = await Promise.all([
      req<WireCostEstimate>('GET', `${t(id)}/cost-estimate`),
      req<WireMember[]>('GET', `${t(id)}/members`),
    ])
    const perPerson = parseFloat(wire.per_person_total)
    const transport = parseFloat(wire.transport_per_person)
    const estimate: CostEstimate = {
      per_member: members
        .filter((m) => m.status === 'joined')
        .map((m) => ({
          user_id: m.user_id,
          admission_usd: perPerson,
          transport_usd: transport,
          meals_usd: 0,
          total_usd: perPerson + transport,
        })),
      assumptions: [
        `Admission for ${wire.priced_stop_count} of ${wire.itinerary_stop_count} planned stops is priced from the destination catalog (${wire.currency}).`,
        ...(wire.unpriced_stop_count > 0
          ? [`${wire.unpriced_stop_count} stop${wire.unpriced_stop_count === 1 ? '' : 's'} without a known admission price ${wire.unpriced_stop_count === 1 ? 'is' : 'are'} excluded.`]
          : []),
        'The same admission estimate applies to every traveler.',
        `Transport: ${wire.transit_leg_count} transit leg${wire.transit_leg_count === 1 ? '' : 's'} at $${wire.transit_fare} and ${wire.taxi_leg_count} taxi leg${wire.taxi_leg_count === 1 ? '' : 's'} at $${wire.taxi_fare_per_person} per person (shared cab); walking is free.`,
        'Meals are not estimated yet.',
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

  // Street paths for every leg (OSRM), including each day's ride back to the hotel.
  getItineraryRoutes: (id) => req<RouteLeg[]>('GET', `${t(id)}/itinerary/routes`),

  // Tasks and packing list ---------------------------------------------------
  listTasks: (id) => req<Task[]>('GET', `${t(id)}/tasks`),
  addTask: (id, title, dueDate) => req<Task>('POST', `${t(id)}/tasks`, { title, due_date: dueDate }),
  setTaskStatus: (id, taskId, status) => req<Task>('PATCH', `${t(id)}/tasks/${taskId}`, { status }),
  deleteTask: (id, taskId) => req<void>('DELETE', `${t(id)}/tasks/${taskId}`),

  listPacking: (id) => req<PackingItem[]>('GET', `${t(id)}/packing`),
  addPacking: (id, label, assigneeId) =>
    req<PackingItem>('POST', `${t(id)}/packing`, { label, assignee_id: assigneeId }),
  updatePacking: (id, item) =>
    req<PackingItem>('PUT', `${t(id)}/packing/${item.item_id}`, {
      label: item.label,
      packed: item.packed,
      assignee_id: item.assignee_id,
    }),
  deletePacking: (id, itemId) => req<void>('DELETE', `${t(id)}/packing/${itemId}`),
}

// The one method the backend does not implement yet, correctDuration, is
// intentionally absent from realApi; src/api/index.ts fills it (mock in hybrid
// mode, 501 in real mode).
