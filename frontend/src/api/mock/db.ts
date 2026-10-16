// In-memory mock database, persisted to localStorage so the demo survives reloads.
import type {
  City,
  Destination,
  Expense,
  Itinerary,
  LockRequest,
  MembershipStatus,
  PackingItem,
  Role,
  Task,
  Trip,
  User,
  UUID,
} from '../types'
import {
  SEED_CITIES,
  SEED_DESTINATIONS,
  SEED_EXPENSES,
  SEED_MEMBERSHIPS,
  SEED_PACKING,
  SEED_TRIP,
  SEED_USERS,
  seedComparisons,
  seedPreferences,
} from './seed'

export interface MockMembership {
  trip_id: UUID
  user_id: UUID
  role: Role
  status: MembershipStatus
}

export interface MockPreference {
  trip_id: UUID
  user_id: UUID
  destination_id: UUID
  points: number
  rank: number | null
  hard_no: boolean
}

export interface MockComparison {
  trip_id: UUID
  user_id: UUID
  dest_a: UUID
  dest_b: UUID
  chosen: UUID
  created_at: string
}

export interface MockState {
  version: number
  sessionUserId: UUID | null
  users: (User & { password: string })[]
  cities: City[]
  destinations: Destination[]
  /** F14: user-reported visit durations, keyed by destination_id */
  durationCorrections: Record<UUID, number[]>
  trips: Trip[]
  memberships: MockMembership[]
  /** Which members have pressed "submit" on their point allocation */
  preferencesSubmitted: { trip_id: UUID; user_id: UUID }[]
  preferences: MockPreference[]
  comparisons: MockComparison[]
  itineraries: Itinerary[]
  /** F12 locks survive regeneration */
  locks: (LockRequest & { trip_id: UUID; destination_id: UUID })[]
  tasks: Task[]
  /** Auto task ids the user deleted, so regeneration doesn't resurrect them */
  dismissedAutoTasks: string[]
  expenses: Expense[]
  packing: (PackingItem & { trip_id: UUID })[]
}

const KEY = 'zoba-mock-db'
const VERSION = 1

function fresh(): MockState {
  return {
    version: VERSION,
    sessionUserId: null,
    users: SEED_USERS.map((u) => ({ ...u, password: 'zoba' })),
    cities: SEED_CITIES,
    destinations: SEED_DESTINATIONS,
    durationCorrections: {},
    trips: [SEED_TRIP],
    memberships: SEED_MEMBERSHIPS,
    preferencesSubmitted: ['u-maya', 'u-jordan', 'u-sam'].map((user_id) => ({ trip_id: SEED_TRIP.trip_id, user_id })),
    preferences: seedPreferences(),
    comparisons: seedComparisons(),
    itineraries: [],
    locks: [],
    tasks: [],
    dismissedAutoTasks: [],
    expenses: SEED_EXPENSES,
    packing: SEED_PACKING,
  }
}

// Shared data lives in localStorage (all tabs); the logged-in user lives in
// sessionStorage (per tab), so two tabs can act as two different travelers.
const SESSION_KEY = 'zoba-mock-session'

function loadSession(): UUID | null {
  try {
    return sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function load(): MockState {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as MockState
      if (parsed.version === VERSION) return { ...parsed, sessionUserId: loadSession() }
    }
  } catch {
    // storage unavailable or corrupt — fall through to seed data
  }
  return { ...fresh(), sessionUserId: loadSession() }
}

export const db: MockState = load()

/** Pick up writes made by other tabs before handling a request. */
export function refresh() {
  Object.assign(db, load())
}

export function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...db, sessionUserId: null }))
    if (db.sessionUserId) sessionStorage.setItem(SESSION_KEY, db.sessionUserId)
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // ignore (private mode, quota)
  }
}

export function resetMockDb() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
  Object.assign(db, fresh())
}

export function newId(prefix: string): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36)
  return `${prefix}-${rand}`
}
