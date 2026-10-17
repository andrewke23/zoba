// FastAPI client. Endpoint paths here are a *proposal* for the backend — keep this
// file and the backend routes in sync. Enabled with VITE_USE_MOCK=false.
import { ApiError } from './types'
import type {
  ComparisonPair,
  ExpenseInput,
  ISODate,
  Itinerary,
  LockRequest,
  PackingItem,
  Preference,
  SolverKind,
  Task,
  TripInput,
  User,
  UUID,
  ZobaApi,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api'

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
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

export const httpApi: ZobaApi = {
  currentUser: () => nullOn(401, req<User>('GET', '/auth/me')),
  register: (email, password, display_name) => req('POST', '/auth/register', { email, password, display_name }),
  login: (email, password) => req('POST', '/auth/login', { email, password }),
  logout: () => req('POST', '/auth/logout'),

  listCities: () => req('GET', '/cities'),
  listTrips: () => req('GET', '/trips'),
  getTrip: (id) => req('GET', t(id)),
  createTrip: (input: TripInput) => req('POST', '/trips', input),
  updateTrip: (id, input: TripInput) => req('PUT', t(id), input),
  getInvite: (token) => req('GET', `/invites/${token}`),
  joinTrip: (token) => req('POST', `/invites/${token}/join`),
  listMembers: (id) => req('GET', `${t(id)}/members`),
  removeMember: (id, userId) => req('DELETE', `${t(id)}/members/${userId}`),

  listDestinations: (id) => req('GET', `${t(id)}/destinations`),
  getPreferenceConfig: (id) => req('GET', `${t(id)}/preferences/config`),
  getMyPreferences: (id) => req('GET', `${t(id)}/preferences/me`),
  saveMyPreferences: (id, prefs: Preference[]) => req('PUT', `${t(id)}/preferences/me`, prefs),

  getComparisonProgress: (id) => req('GET', `${t(id)}/comparisons/me`),
  submitComparison: (id, pair: ComparisonPair, chosen) => req('POST', `${t(id)}/comparisons`, { ...pair, chosen }),

  getGroupResults: (id) => req('GET', `${t(id)}/results`),

  getItinerary: (id) => nullOn(404, req<Itinerary>('GET', `${t(id)}/itinerary`)),
  generateItinerary: (id, solver: SolverKind) => req('POST', `${t(id)}/itinerary/generate`, { solver }),
  setStopLock: (id, destId, lock: LockRequest | null) => req('PUT', `${t(id)}/itinerary/locks/${destId}`, lock),
  correctDuration: (id, destId, minutes) => req('POST', `${t(id)}/destinations/${destId}/duration`, { minutes }),
  compareSolvers: (id) => req('POST', `${t(id)}/itinerary/compare`),

  listTasks: (id) => req('GET', `${t(id)}/tasks`),
  addTask: (id, title, due_date: ISODate | null) => req('POST', `${t(id)}/tasks`, { title, due_date }),
  setTaskStatus: (id, taskId, status: Task['status']) => req('PATCH', `${t(id)}/tasks/${taskId}`, { status }),
  deleteTask: (id, taskId) => req('DELETE', `${t(id)}/tasks/${taskId}`),
  getCostEstimate: (id) => req('GET', `${t(id)}/costs`),
  listExpenses: (id) => req('GET', `${t(id)}/expenses`),
  addExpense: (id, input: ExpenseInput) => req('POST', `${t(id)}/expenses`, input),
  deleteExpense: (id, expenseId) => req('DELETE', `${t(id)}/expenses/${expenseId}`),
  getSettlement: (id) => req('GET', `${t(id)}/settlement`),

  listPacking: (id) => req('GET', `${t(id)}/packing`),
  addPacking: (id, label, assignee_id) => req('POST', `${t(id)}/packing`, { label, assignee_id }),
  updatePacking: (id, item: PackingItem) => req('PUT', `${t(id)}/packing/${item.item_id}`, item),
  deletePacking: (id, itemId) => req('DELETE', `${t(id)}/packing/${itemId}`),
}
