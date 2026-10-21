// Chooses the API implementation per mode:
//
//   mock    — everything is the in-browser mock (demo mode, no server needed)
//   hybrid  — default: real backend where it exists, mock elsewhere
//   real    — everything must be real; unimplemented endpoints fail with 501
//
// The real backend currently covers auth, cities, trips, invites/members,
// expenses, settlement, and the cost estimate. Preferences, comparisons,
// group results, itinerary/solvers, tasks, and packing are still mock-only
// (see src/api/http.ts), so hybrid keeps the whole app usable meanwhile.
import { realApi } from './http'
import { hybridBridge, mockApi } from './mock'
import { ApiError } from './types'
import type { Member, Trip, UUID, ZobaApi } from './types'

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
}

export const api: ZobaApi = mode === 'mock' ? mockApi : mode === 'real' ? rejectUnimplemented(realApi) : hybridApi

export * from './types'
