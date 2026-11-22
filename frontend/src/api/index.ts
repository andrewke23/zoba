// Chooses the API implementation per mode:
//
//   mock    — everything is the in-browser mock (demo mode, no server needed)
//   hybrid  — default: real backend where it exists, mock elsewhere
//   real    — everything must be real; unimplemented endpoints fail with 501
//
// The real backend currently covers auth, cities, trips, invites/members,
// destinations, expenses, settlement, the cost estimate and the itinerary.
// Preferences, comparisons, group results, tasks, and packing are still
// mock-only (see src/api/http.ts), so hybrid keeps the whole app usable
// meanwhile — with the mock voting on the backend's real destination catalog.
import { realApi } from './http'
import { hybridBridge, mockApi } from './mock'
import { ApiError } from './types'
import type { Destination, Member, Trip, UUID, ZobaApi } from './types'

export type ApiMode = 'mock' | 'hybrid' | 'real'

const envMode = import.meta.env.VITE_API_MODE
const mode: ApiMode =
  envMode === 'mock' || envMode === 'real' ? envMode : import.meta.env.VITE_USE_MOCK === 'true' ? 'mock' : 'hybrid'

export const API_MODE: ApiMode = mode
/** True only in pure demo mode: no backend involved at all. */
export const USING_MOCK = mode === 'mock'

/** Fill every method the real API doesn't implement with a clear 501. */
function rejectUnimplemented(base: Partial<ZobaApi>): ZobaApi {
  const out = { ...base } as Record<string, unknown>
  for (const key of Object.keys(mockApi) as (keyof ZobaApi)[]) {
    if (!(key in base)) {
      out[key] = () =>
        Promise.reject(
          new ApiError(501, `${String(key)} isn't served by the backend yet — try demo mode (VITE_API_MODE=mock).`),
        )
    }
  }
  return out as unknown as ZobaApi
}

// Voting progress (preferences/comparisons) is mock-owned until the backend
// grows a preferences domain; membership itself is real. Merge the two so the
// overview and preferences pages get correct flags either way.
async function listMembersWithVotingProgress(tripId: UUID): Promise<Member[]> {
  const members = await realApi.listMembers!(tripId)
  hybridBridge.members(tripId, members)
  let progress = new Map<UUID, Pick<Member, 'preferences_submitted' | 'comparisons_done'>>()
  try {
    const mockMembers = await mockApi.listMembers(tripId)
    progress = new Map(
      mockMembers.map((m) => [m.user_id, { preferences_submitted: m.preferences_submitted, comparisons_done: m.comparisons_done }]),
    )
  } catch {
    // Trip isn't in the mock database — no demo voting data to merge in.
  }
  return members.map((m) => ({ ...m, ...progress.get(m.user_id) }))
}

function mirrorTrip(trip: Trip): Trip {
  hybridBridge.trip(trip)
  return trip
}

// The mock's voting pages only know the places in its own catalog (demo
// Chicago). Before any of them runs, copy the trip city's real places in, once
// per trip per page load, so every city works and votes use real IDs.
const destinationSync = new Map<UUID, Promise<Destination[]>>()

function realDestinations(tripId: UUID): Promise<Destination[]> {
  let pending = destinationSync.get(tripId)
  if (!pending) {
    pending = realApi.listDestinations!(tripId).then((destinations) => {
      hybridBridge.destinations(destinations)
      return destinations
    })
    // A failed fetch shouldn't stick: let the next call retry.
    pending.catch(() => destinationSync.delete(tripId))
    destinationSync.set(tripId, pending)
  }
  return pending
}

/** Wrap a mock-served method so it runs against the trip's real places. */
function withRealDestinations<A extends unknown[], R>(fn: (tripId: UUID, ...args: A) => Promise<R>) {
  return async (tripId: UUID, ...args: A): Promise<R> => {
    await realDestinations(tripId)
    return fn(tripId, ...args)
  }
}

// Sign-in and trips are real; each result is mirrored into the mock so the
// mock-served pages know who is signed in and which trips exist.
const hybridApi: ZobaApi = {
  ...mockApi,
  ...realApi,
  currentUser: async () => {
    const user = await realApi.currentUser!()
    if (user) hybridBridge.signIn(user)
    else hybridBridge.signOut()
    return user
  },
  register: async (email, password, displayName) => {
    const user = await realApi.register!(email, password, displayName)
    hybridBridge.signIn(user)
    return user
  },
  login: async (email, password) => {
    const user = await realApi.login!(email, password)
    hybridBridge.signIn(user)
    return user
  },
  logout: async () => {
    await realApi.logout!()
    hybridBridge.signOut()
  },
  getTrip: async (tripId) => mirrorTrip(await realApi.getTrip!(tripId)),
  createTrip: async (input) => mirrorTrip(await realApi.createTrip!(input)),
  updateTrip: async (tripId, input) => mirrorTrip(await realApi.updateTrip!(tripId, input)),
  joinTrip: async (token) => mirrorTrip(await realApi.joinTrip!(token)),
  listMembers: listMembersWithVotingProgress,
  listDestinations: realDestinations,
  getMyPreferences: withRealDestinations(mockApi.getMyPreferences),
  saveMyPreferences: withRealDestinations(mockApi.saveMyPreferences),
  getComparisonProgress: withRealDestinations(mockApi.getComparisonProgress),
  submitComparison: withRealDestinations(mockApi.submitComparison),
  getGroupResults: withRealDestinations(mockApi.getGroupResults),
  correctDuration: withRealDestinations(mockApi.correctDuration),
}

export const api: ZobaApi = mode === 'mock' ? mockApi : mode === 'real' ? rejectUnimplemented(realApi) : hybridApi

export * from './types'
