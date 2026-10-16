// Shared frontend models. Field names mirror data-pipeline/db/schema.sql so the
// real FastAPI responses can drop in without reshaping.

export type UUID = string
/** ISO date, e.g. "2026-11-06" */
export type ISODate = string
/** ISO timestamp */
export type ISODateTime = string
/** 24h local time, e.g. "09:00" */
export type HHMM = string

export type Category =
  | 'museum'
  | 'landmark'
  | 'park'
  | 'viewpoint'
  | 'entertainment'
  | 'food'
  | 'cafe'
  | 'nightlife'
  | 'shopping'
  | 'other'

export interface User {
  user_id: UUID
  email: string
  display_name: string
}

export interface City {
  city_id: string
  name: string
  /** [lng, lat] map center */
  center: [number, number]
  timezone: string
}

export interface HomeBase {
  label: string
  lat: number
  lng: number
}

export interface Trip {
  trip_id: UUID
  name: string
  organizer_id: UUID
  city_id: string
  start_date: ISODate
  end_date: ISODate
  day_start: HHMM
  day_end: HHMM
  home_base: HomeBase
  invite_token: string
  created_at: ISODateTime
}

export type TripInput = Omit<Trip, 'trip_id' | 'organizer_id' | 'invite_token' | 'created_at'>

export type Role = 'organizer' | 'member'
export type MembershipStatus = 'invited' | 'joined' | 'left'

export interface Member {
  user_id: UUID
  email: string
  display_name: string
  role: Role
  status: MembershipStatus
  /** Has submitted F07a point allocation */
  preferences_submitted: boolean
  comparisons_done: number
}

export interface TripSummary extends Trip {
  city_name: string
  my_role: Role
  member_count: number
}

export interface OpeningWindow {
  /** 0 = Mon … 6 = Sun */
  weekday: number
  open_min: number
  /** may exceed 1440 for windows that run past midnight */
  close_min: number
}

export interface Destination {
  destination_id: UUID
  city_id: string
  name: string
  lat: number
  lng: number
  category: Category
  address: string | null
  website: string | null
  description: string | null
  admission_cost_usd: number | null
  est_duration_min: number
  hours: OpeningWindow[]
  hours_status: 'ok' | 'partial' | 'unparseable' | 'missing'
  /** Needs advance booking → generates a task (F15) */
  requires_booking: boolean
}

// ---- Preferences (F07a, F08) ----

export interface Preference {
  destination_id: UUID
  points: number
  rank: number | null
  hard_no: boolean
}

export interface PreferenceConfig {
  /** Fixed point budget each member allocates (F07a) */
  point_budget: number
  /** Max points that count toward weight for a single destination (F08a) */
  point_cap: number
  /** Comparisons a member should complete (SRS §8 open question) */
  target_comparisons: number
}

// ---- Pairwise comparisons (F03, F04) ----

export interface ComparisonPair {
  dest_a: UUID
  dest_b: UUID
}

export interface ComparisonProgress {
  done: number
  target: number
  /** null when no more informative pairs remain */
  next: ComparisonPair | null
}

// ---- Group results (F06, F08a) ----

export interface RankingRow {
  destination_id: UUID
  rank: number
  /** Sum of raw points from all members */
  raw_points: number
  /** Number of members who gave it any points */
  raw_votes: number
  /** Capped, normalized point weight (0..1) */
  weighted_points: number
  /** Fairness-aware group score (0..1) */
  group_score: number
  /** Lowest single-member utility for this destination (0..1) */
  min_member_utility: number
  vetoed_by: UUID[]
}

export interface MemberTopPick {
  user_id: UUID
  destination_id: UUID | null
}

export interface GroupResults {
  rows: RankingRow[]
  top_picks: MemberTopPick[]
  config: PreferenceConfig
  computed_at: ISODateTime
}

// ---- Itinerary (F09–F14) ----

export type SolverKind = 'greedy' | 'cpsat'
export type TravelMode = 'walk' | 'drive' | 'transit'

export interface ItineraryStop {
  trip_id: UUID
  day_index: number
  seq: number
  destination_id: UUID
  start_ts: ISODateTime
  end_ts: ISODateTime
  locked: boolean
  travel_min_from_prev: number
  travel_mode_from_prev: TravelMode
}

export interface ItineraryDay {
  day_index: number
  date: ISODate
  stops: ItineraryStop[]
}

export interface Unscheduled {
  destination_id: UUID
  reason: string
}

export interface TopPickStatus {
  user_id: UUID
  destination_id: UUID | null
  included: boolean
  reason: string | null
}

export interface SolverMetrics {
  solver: SolverKind
  runtime_ms: number
  group_score: number
  min_member_utility: number
  stops_scheduled: number
  travel_min_total: number
  feasible: boolean
}

export interface Itinerary {
  trip_id: UUID
  solver: SolverKind
  generated_at: ISODateTime
  days: ItineraryDay[]
  unscheduled: Unscheduled[]
  top_picks: TopPickStatus[]
  conflicts: string[]
  metrics: SolverMetrics
}

export interface LockRequest {
  day_index: number
  start_ts: ISODateTime
}

// ---- Trip prep (F15–F17, packing) ----

export interface Task {
  task_id: UUID
  trip_id: UUID
  title: string
  due_date: ISODate | null
  status: 'open' | 'done'
  destination_id: UUID | null
  auto_generated: boolean
  booking_url: string | null
}

export interface CostLine {
  user_id: UUID
  admission_usd: number
  transport_usd: number
  meals_usd: number
  total_usd: number
}

export interface CostEstimate {
  per_member: CostLine[]
  assumptions: string[]
}

export interface ExpenseShare {
  user_id: UUID
  share_cents: number
}

export interface Expense {
  expense_id: UUID
  trip_id: UUID
  payer_id: UUID
  amount_cents: number
  description: string
  created_at: ISODateTime
  shares: ExpenseShare[]
}

export interface ExpenseInput {
  payer_id: UUID
  amount_cents: number
  description: string
  shares: ExpenseShare[]
}

export interface Balance {
  user_id: UUID
  paid_cents: number
  owed_cents: number
  /** positive = should receive money */
  net_cents: number
}

export interface Transfer {
  from_user_id: UUID
  to_user_id: UUID
  amount_cents: number
}

export interface Settlement {
  balances: Balance[]
  transfers: Transfer[]
}

export interface PackingItem {
  item_id: UUID
  label: string
  packed: boolean
  /** null = everyone brings their own */
  assignee_id: UUID | null
}

// ---- API contract ----

export interface ZobaApi {
  // Auth (F01)
  currentUser(): Promise<User | null>
  register(email: string, password: string, displayName: string): Promise<User>
  login(email: string, password: string): Promise<User>
  logout(): Promise<void>

  // Trips (F02) + membership
  listCities(): Promise<City[]>
  listTrips(): Promise<TripSummary[]>
  getTrip(tripId: UUID): Promise<Trip>
  createTrip(input: TripInput): Promise<Trip>
  updateTrip(tripId: UUID, input: TripInput): Promise<Trip>
  getInvite(token: string): Promise<{ trip: Trip; city_name: string; organizer_name: string }>
  joinTrip(token: string): Promise<Trip>
  listMembers(tripId: UUID): Promise<Member[]>
  removeMember(tripId: UUID, userId: UUID): Promise<void>

  // Destinations + preferences (F07a, F08)
  listDestinations(tripId: UUID): Promise<Destination[]>
  getPreferenceConfig(tripId: UUID): Promise<PreferenceConfig>
  getMyPreferences(tripId: UUID): Promise<Preference[]>
  saveMyPreferences(tripId: UUID, prefs: Preference[]): Promise<void>

  // Comparisons (F03, F04)
  getComparisonProgress(tripId: UUID): Promise<ComparisonProgress>
  submitComparison(tripId: UUID, pair: ComparisonPair, chosen: UUID): Promise<ComparisonProgress>

  // Group ranking (F06, F08a)
  getGroupResults(tripId: UUID): Promise<GroupResults>

  // Itinerary (F09–F14)
  getItinerary(tripId: UUID): Promise<Itinerary | null>
  generateItinerary(tripId: UUID, solver: SolverKind): Promise<Itinerary>
  setStopLock(tripId: UUID, destinationId: UUID, lock: LockRequest | null): Promise<Itinerary>
  correctDuration(tripId: UUID, destinationId: UUID, minutes: number): Promise<Destination>
  compareSolvers(tripId: UUID): Promise<SolverMetrics[]>

  // Prep (F15–F17)
  listTasks(tripId: UUID): Promise<Task[]>
  addTask(tripId: UUID, title: string, dueDate: ISODate | null): Promise<Task>
  setTaskStatus(tripId: UUID, taskId: UUID, status: Task['status']): Promise<Task>
  deleteTask(tripId: UUID, taskId: UUID): Promise<void>
  getCostEstimate(tripId: UUID): Promise<CostEstimate>
  listExpenses(tripId: UUID): Promise<Expense[]>
  addExpense(tripId: UUID, input: ExpenseInput): Promise<Expense>
  deleteExpense(tripId: UUID, expenseId: UUID): Promise<void>
  getSettlement(tripId: UUID): Promise<Settlement>

  // Packing list (no requirement ID yet — SRS §8)
  listPacking(tripId: UUID): Promise<PackingItem[]>
  addPacking(tripId: UUID, label: string, assigneeId: UUID | null): Promise<PackingItem>
  updatePacking(tripId: UUID, item: PackingItem): Promise<PackingItem>
  deletePacking(tripId: UUID, itemId: UUID): Promise<void>
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
