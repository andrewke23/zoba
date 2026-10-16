// Mock implementation of ZobaApi. Swap for httpApi via VITE_USE_MOCK=false.
import { ApiError } from '../types'
import type {
  CostEstimate,
  Destination,
  Itinerary,
  Member,
  Preference,
  SolverKind,
  SolverMetrics,
  Task,
  Trip,
  User,
  UUID,
  ZobaApi,
} from '../types'
import { PREF_CONFIG, balances, computeRanking, nextPair, schedule, settle, tripDates } from './algorithms'
import { db, newId, persist, refresh } from './db'
import { SEED_DESTINATIONS } from './seed'

/** SRS §8 leaves lock authority open; F12 says members may lock. Flip to restrict to organizers. */
export const MEMBERS_CAN_LOCK = true

const clone = <T>(x: T): T => structuredClone(x)
const delay = (ms = 120 + Math.random() * 180) => new Promise((r) => setTimeout(r, ms))

async function respond<T>(fn: () => T): Promise<T> {
  await delay()
  refresh()
  const out = fn()
  persist()
  return clone(out)
}

function me(): User {
  const u = db.users.find((x) => x.user_id === db.sessionUserId)
  if (!u) throw new ApiError(401, 'Please log in.')
  return { user_id: u.user_id, email: u.email, display_name: u.display_name }
}

function trip(tripId: UUID): Trip {
  const t = db.trips.find((x) => x.trip_id === tripId)
  if (!t) throw new ApiError(404, 'Trip not found.')
  return t
}

function membership(tripId: UUID) {
  const user = me()
  trip(tripId)
  const m = db.memberships.find((x) => x.trip_id === tripId && x.user_id === user.user_id && x.status === 'joined')
  if (!m) throw new ApiError(403, "You're not a member of this trip.")
  return m
}

function organizer(tripId: UUID) {
  const m = membership(tripId)
  if (m.role !== 'organizer') throw new ApiError(403, 'Only the organizer can do that.')
  return m
}

const joinedIds = (tripId: UUID) =>
  db.memberships.filter((m) => m.trip_id === tripId && m.status === 'joined').map((m) => m.user_id)

const tripDestinations = (tripId: UUID) => db.destinations.filter((d) => d.city_id === trip(tripId).city_id)

function ranking(tripId: UUID) {
  return computeRanking(
    tripDestinations(tripId),
    joinedIds(tripId),
    db.preferences.filter((p) => p.trip_id === tripId),
    db.comparisons.filter((c) => c.trip_id === tripId),
  )
}

function buildItinerary(tripId: UUID, solver: SolverKind): Itinerary {
  const t = trip(tripId)
  const dests = new Map(tripDestinations(tripId).map((d) => [d.destination_id, d]))
  const r = ranking(tripId)
  const candidates = r.rows.filter((row) => !r.vetoed.has(row.destination_id)).map((row) => ({ id: row.destination_id, score: row.group_score }))
  const topPickIds = [...new Set([...r.topPicks.values()].filter((x): x is UUID => x !== null))]
  const locks = db.locks.filter((l) => l.trip_id === tripId)

  const t0 = performance.now()
  const out = schedule({ trip: t, destinations: dests, candidates, mustInclude: topPickIds, locks, solver })
  const runtime = performance.now() - t0

  const scheduled = out.days.flatMap((d) => d.stops.map((s) => s.destination_id))
  const scheduledSet = new Set(scheduled)
  const k = scheduled.length

  const topK = (vals: number[]) => vals.sort((a, b) => b - a).slice(0, k).reduce((s, x) => s + x, 0) || 1
  const groupScore = scheduled.reduce((s, id) => s + (r.rows.find((x) => x.destination_id === id)?.group_score ?? 0), 0) / topK(candidates.map((c) => c.score))
  const memberShares = [...r.utility.values()].map((u) => {
    const got = scheduled.reduce((s, id) => s + (u.get(id) ?? 0), 0)
    return got / topK(candidates.map((c) => u.get(c.id) ?? 0))
  })

  const conflicts = [...out.conflicts]
  const top_picks = joinedIds(tripId).map((uid) => {
    const pick = r.topPicks.get(uid) ?? null
    const included = pick !== null && scheduledSet.has(pick)
    let reason: string | null = null
    if (pick === null) reason = 'No preferences submitted yet'
    else if (!included) {
      reason = out.unplaced.get(pick) ?? 'Could not be scheduled'
      const name = db.users.find((u) => u.user_id === uid)?.display_name ?? 'A member'
      conflicts.push(`${name}'s top pick (${dests.get(pick)?.name}) couldn't be included: ${reason}.`)
    }
    return { user_id: uid, destination_id: pick, included, reason }
  })

  const unscheduled = [
    ...[...r.vetoed].map((id) => ({ destination_id: id, reason: 'Vetoed (hard no)' })),
    ...r.rows
      .filter((row) => out.unplaced.has(row.destination_id) && (row.rank <= 12 || topPickIds.includes(row.destination_id)))
      .map((row) => ({ destination_id: row.destination_id, reason: out.unplaced.get(row.destination_id)! })),
  ]

  for (const d of dests.values()) {
    if (scheduledSet.has(d.destination_id) && (d.hours_status === 'missing' || d.hours_status === 'unparseable')) {
      conflicts.push(`Opening hours for ${d.name} are unknown — assumed open. Double-check before you go.`)
    }
  }

  const metrics: SolverMetrics = {
    solver,
    runtime_ms: Math.round(runtime * 100) / 100,
    group_score: groupScore,
    min_member_utility: memberShares.length ? Math.min(...memberShares) : 0,
    stops_scheduled: k,
    travel_min_total: out.days.flatMap((d) => d.stops).reduce((s, x) => s + x.travel_min_from_prev, 0),
    feasible: out.conflicts.length === 0,
  }

  return {
    trip_id: tripId,
    solver,
    generated_at: new Date().toISOString(),
    days: out.days,
    unscheduled,
    top_picks,
    conflicts,
    metrics,
  }
}

function saveItinerary(it: Itinerary) {
  db.itineraries = db.itineraries.filter((x) => x.trip_id !== it.trip_id).concat(it)
  syncAutoTasks(it)
}

/** F15: one booking task per scheduled stop that needs advance booking, due a week before. */
function syncAutoTasks(it: Itinerary) {
  const wanted = new Map<string, Task>()
  for (const day of it.days) {
    for (const s of day.stops) {
      const d = db.destinations.find((x) => x.destination_id === s.destination_id)
      if (!d?.requires_booking) continue
      const task_id = `auto-${it.trip_id}-${d.destination_id}`
      if (db.dismissedAutoTasks.includes(task_id)) continue
      const due = new Date(`${day.date}T00:00:00Z`)
      due.setUTCDate(due.getUTCDate() - 7)
      wanted.set(task_id, {
        task_id,
        trip_id: it.trip_id,
        title: `Book ${d.name} (Day ${day.day_index + 1}, ${s.start_ts.slice(11, 16)})`,
        due_date: due.toISOString().slice(0, 10),
        status: 'open',
        destination_id: d.destination_id,
        auto_generated: true,
        booking_url: d.website,
      })
    }
  }
  db.tasks = db.tasks
    .filter((t) => t.trip_id !== it.trip_id || !t.auto_generated || wanted.has(t.task_id) || t.status === 'done')
    .map((t) => (wanted.has(t.task_id) ? { ...wanted.get(t.task_id)!, status: t.status } : t))
  for (const [id, task] of wanted) if (!db.tasks.some((t) => t.task_id === id)) db.tasks.push(task)
}

const MEAL_AVG_USD = 20
const MEALS_PER_DAY = 3
const TRANSIT_FARE_USD = 2.5

function costEstimate(tripId: UUID): CostEstimate {
  const it = db.itineraries.find((x) => x.trip_id === tripId)
  const t = trip(tripId)
  const days = tripDates(t).length
  const stops = it?.days.flatMap((d) => d.stops) ?? []
  const destOf = (id: UUID) => db.destinations.find((d) => d.destination_id === id)!
  let admission = 0
  let foodStops = 0
  let foodCost = 0
  let transit = 0
  for (const s of stops) {
    const d = destOf(s.destination_id)
    if (d.category === 'food') {
      foodStops++
      foodCost += d.admission_cost_usd ?? MEAL_AVG_USD
    } else admission += d.admission_cost_usd ?? 0
    if (s.travel_mode_from_prev === 'transit') transit++
  }
  if (stops.length) transit++ // ride back to home base at the end of the day (approx.)
  const meals = foodCost + Math.max(0, days * MEALS_PER_DAY - foodStops) * MEAL_AVG_USD
  const transport = transit * TRANSIT_FARE_USD
  return {
    per_member: joinedIds(tripId).map((user_id) => ({
      user_id,
      admission_usd: admission,
      transport_usd: transport,
      meals_usd: meals,
      total_usd: admission + transport + meals,
    })),
    assumptions: [
      it ? `Based on the current itinerary (${stops.length} stops over ${days} days).` : 'No itinerary yet — only meals are estimated.',
      `Meals not covered by a scheduled restaurant use a category average of $${MEAL_AVG_USD}, ${MEALS_PER_DAY} per day.`,
      `Transit legs use a flat $${TRANSIT_FARE_USD.toFixed(2)} fare; walking legs are free.`,
      'Unknown admission prices count as $0.',
    ],
  }
}

function currentDuration(destId: UUID): number {
  const base = SEED_DESTINATIONS.find((d) => d.destination_id === destId)?.est_duration_min ?? 60
  const cs = db.durationCorrections[destId] ?? []
  // Prior counts as one observation; corrections pull the estimate toward reality.
  return Math.round((base + cs.reduce((s, x) => s + x, 0)) / (1 + cs.length))
}

export const mockApi: ZobaApi = {
  currentUser: () => respond(() => (db.sessionUserId ? me() : null)),

  register: (email, password, displayName) =>
    respond(() => {
      const e = email.trim().toLowerCase()
      if (!e.includes('@')) throw new ApiError(400, 'Enter a valid email.')
      if (password.length < 4) throw new ApiError(400, 'Password must be at least 4 characters.')
      if (db.users.some((u) => u.email === e)) throw new ApiError(409, 'An account with that email already exists.')
      const user = { user_id: newId('u'), email: e, display_name: displayName.trim() || e.split('@')[0], password }
      db.users.push(user)
      db.sessionUserId = user.user_id
      return me()
    }),

  login: (email, password) =>
    respond(() => {
      const u = db.users.find((x) => x.email === email.trim().toLowerCase())
      if (!u || u.password !== password) throw new ApiError(401, 'Incorrect email or password.')
      db.sessionUserId = u.user_id
      return me()
    }),

  logout: () =>
    respond(() => {
      db.sessionUserId = null
    }),

  listCities: () => respond(() => db.cities),

  listTrips: () =>
    respond(() => {
      const user = me()
      return db.memberships
        .filter((m) => m.user_id === user.user_id && m.status === 'joined')
        .map((m) => {
          const t = trip(m.trip_id)
          return {
            ...t,
            city_name: db.cities.find((c) => c.city_id === t.city_id)?.name ?? t.city_id,
            my_role: m.role,
            member_count: joinedIds(t.trip_id).length,
          }
        })
        .sort((a, b) => a.start_date.localeCompare(b.start_date))
    }),

  getTrip: (tripId) =>
    respond(() => {
      membership(tripId)
      return trip(tripId)
    }),

  createTrip: (input) =>
    respond(() => {
      const user = me()
      if (input.end_date < input.start_date) throw new ApiError(400, 'End date must be on or after the start date.')
      if (input.day_end <= input.day_start) throw new ApiError(400, 'Daily end time must be after the start time.')
      const t: Trip = {
        ...input,
        trip_id: newId('t'),
        organizer_id: user.user_id,
        invite_token: newId('inv').slice(0, 14),
        created_at: new Date().toISOString(),
      }
      db.trips.push(t)
      db.memberships.push({ trip_id: t.trip_id, user_id: user.user_id, role: 'organizer', status: 'joined' })
      return t
    }),

  updateTrip: (tripId, input) =>
    respond(() => {
      organizer(tripId)
      if (input.end_date < input.start_date) throw new ApiError(400, 'End date must be on or after the start date.')
      if (input.day_end <= input.day_start) throw new ApiError(400, 'Daily end time must be after the start time.')
      const t = trip(tripId)
      Object.assign(t, input)
      return t
    }),

  getInvite: (token) =>
    respond(() => {
      const t = db.trips.find((x) => x.invite_token === token)
      if (!t) throw new ApiError(404, 'This invite link is invalid or has expired.')
      return {
        trip: t,
        city_name: db.cities.find((c) => c.city_id === t.city_id)?.name ?? t.city_id,
        organizer_name: db.users.find((u) => u.user_id === t.organizer_id)?.display_name ?? 'The organizer',
      }
    }),

  joinTrip: (token) =>
    respond(() => {
      const user = me()
      const t = db.trips.find((x) => x.invite_token === token)
      if (!t) throw new ApiError(404, 'This invite link is invalid or has expired.')
      const existing = db.memberships.find((m) => m.trip_id === t.trip_id && m.user_id === user.user_id)
      if (existing) existing.status = 'joined'
      else {
        if (joinedIds(t.trip_id).length >= 8) throw new ApiError(400, 'This trip already has 8 travelers (the maximum).')
        db.memberships.push({ trip_id: t.trip_id, user_id: user.user_id, role: 'member', status: 'joined' })
      }
      return t
    }),

  listMembers: (tripId) =>
    respond(() => {
      membership(tripId)
      return db.memberships
        .filter((m) => m.trip_id === tripId && m.status !== 'left')
        .map((m): Member => {
          const u = db.users.find((x) => x.user_id === m.user_id)!
          return {
            user_id: u.user_id,
            email: u.email,
            display_name: u.display_name,
            role: m.role,
            status: m.status,
            preferences_submitted: db.preferencesSubmitted.some((p) => p.trip_id === tripId && p.user_id === u.user_id),
            comparisons_done: db.comparisons.filter((c) => c.trip_id === tripId && c.user_id === u.user_id).length,
          }
        })
    }),

  removeMember: (tripId, userId) =>
    respond(() => {
      organizer(tripId)
      if (userId === trip(tripId).organizer_id) throw new ApiError(400, "The organizer can't be removed.")
      const m = db.memberships.find((x) => x.trip_id === tripId && x.user_id === userId)
      if (m) m.status = 'left'
    }),

  listDestinations: (tripId) =>
    respond(() => {
      membership(tripId)
      return tripDestinations(tripId)
    }),

  getPreferenceConfig: (tripId) =>
    respond(() => {
      membership(tripId)
      return PREF_CONFIG
    }),

  getMyPreferences: (tripId) =>
    respond(() => {
      const m = membership(tripId)
      return db.preferences
        .filter((p) => p.trip_id === tripId && p.user_id === m.user_id)
        .map(({ destination_id, points, rank, hard_no }): Preference => ({ destination_id, points, rank, hard_no }))
    }),

  saveMyPreferences: (tripId, prefs) =>
    respond(() => {
      const m = membership(tripId)
      const total = prefs.reduce((s, p) => s + (p.hard_no ? 0 : p.points), 0)
      if (total > PREF_CONFIG.point_budget) throw new ApiError(400, `You can allocate at most ${PREF_CONFIG.point_budget} points.`)
      if (prefs.some((p) => p.points < 0)) throw new ApiError(400, 'Points cannot be negative.')
      db.preferences = db.preferences
        .filter((p) => !(p.trip_id === tripId && p.user_id === m.user_id))
        .concat(
          prefs
            .filter((p) => p.points > 0 || p.hard_no || p.rank !== null)
            .map((p) => ({ ...p, points: p.hard_no ? 0 : p.points, trip_id: tripId, user_id: m.user_id })),
        )
      if (!db.preferencesSubmitted.some((p) => p.trip_id === tripId && p.user_id === m.user_id)) {
        db.preferencesSubmitted.push({ trip_id: tripId, user_id: m.user_id })
      }
    }),

  getComparisonProgress: (tripId) => respond(() => progress(tripId)),

  submitComparison: (tripId, pair, chosen) =>
    respond(() => {
      const m = membership(tripId)
      if (chosen !== pair.dest_a && chosen !== pair.dest_b) throw new ApiError(400, 'Choice must be one of the pair.')
      db.comparisons.push({ trip_id: tripId, user_id: m.user_id, ...pair, chosen, created_at: new Date().toISOString() })
      return progress(tripId)
    }),

  getGroupResults: (tripId) =>
    respond(() => {
      membership(tripId)
      const r = ranking(tripId)
      return {
        rows: r.rows,
        top_picks: [...r.topPicks].map(([user_id, destination_id]) => ({ user_id, destination_id })),
        config: PREF_CONFIG,
        computed_at: new Date().toISOString(),
      }
    }),

  getItinerary: (tripId) =>
    respond(() => {
      membership(tripId)
      return db.itineraries.find((x) => x.trip_id === tripId) ?? null
    }),

  generateItinerary: (tripId, solver) =>
    respond(() => {
      organizer(tripId)
      const it = buildItinerary(tripId, solver)
      saveItinerary(it)
      return it
    }),

  setStopLock: (tripId, destinationId, lock) =>
    respond(() => {
      if (MEMBERS_CAN_LOCK) membership(tripId)
      else organizer(tripId)
      db.locks = db.locks.filter((l) => !(l.trip_id === tripId && l.destination_id === destinationId))
      if (lock) db.locks.push({ ...lock, trip_id: tripId, destination_id: destinationId })
      // F12: regenerate the remainder around the lock.
      const solver = db.itineraries.find((x) => x.trip_id === tripId)?.solver ?? 'greedy'
      const it = buildItinerary(tripId, solver)
      saveItinerary(it)
      return it
    }),

  correctDuration: (tripId, destinationId, minutes) =>
    respond(() => {
      membership(tripId)
      if (!(minutes >= 5 && minutes <= 600)) throw new ApiError(400, 'Duration must be between 5 and 600 minutes.')
      const d = db.destinations.find((x) => x.destination_id === destinationId)
      if (!d) throw new ApiError(404, 'Destination not found.')
      ;(db.durationCorrections[destinationId] ??= []).push(minutes)
      d.est_duration_min = currentDuration(destinationId)
      return d
    }),

  compareSolvers: (tripId) =>
    respond(() => {
      organizer(tripId)
      return (['greedy', 'cpsat'] as const).map((s) => buildItinerary(tripId, s).metrics)
    }),

  listTasks: (tripId) =>
    respond(() => {
      membership(tripId)
      return db.tasks
        .filter((t) => t.trip_id === tripId)
        .sort((a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999'))
    }),

  addTask: (tripId, title, dueDate) =>
    respond(() => {
      membership(tripId)
      if (!title.trim()) throw new ApiError(400, 'Task needs a title.')
      const task: Task = {
        task_id: newId('task'),
        trip_id: tripId,
        title: title.trim(),
        due_date: dueDate,
        status: 'open',
        destination_id: null,
        auto_generated: false,
        booking_url: null,
      }
      db.tasks.push(task)
      return task
    }),

  setTaskStatus: (tripId, taskId, status) =>
    respond(() => {
      membership(tripId)
      const task = db.tasks.find((t) => t.task_id === taskId && t.trip_id === tripId)
      if (!task) throw new ApiError(404, 'Task not found.')
      task.status = status
      return task
    }),

  deleteTask: (tripId, taskId) =>
    respond(() => {
      membership(tripId)
      const task = db.tasks.find((t) => t.task_id === taskId)
      if (task?.auto_generated) db.dismissedAutoTasks.push(taskId)
      db.tasks = db.tasks.filter((t) => t.task_id !== taskId)
    }),

  getCostEstimate: (tripId) =>
    respond(() => {
      membership(tripId)
      return costEstimate(tripId)
    }),

  listExpenses: (tripId) =>
    respond(() => {
      membership(tripId)
      return db.expenses.filter((e) => e.trip_id === tripId).sort((a, b) => b.created_at.localeCompare(a.created_at))
    }),

  addExpense: (tripId, input) =>
    respond(() => {
      membership(tripId)
      if (input.amount_cents <= 0) throw new ApiError(400, 'Amount must be positive.')
      if (!input.shares.length) throw new ApiError(400, 'Pick at least one person to split with.')
      const sum = input.shares.reduce((s, x) => s + x.share_cents, 0)
      if (sum !== input.amount_cents) throw new ApiError(400, 'Shares must add up to the total.')
      const e = { ...input, expense_id: newId('e'), trip_id: tripId, created_at: new Date().toISOString() }
      db.expenses.push(e)
      return e
    }),

  deleteExpense: (tripId, expenseId) =>
    respond(() => {
      membership(tripId)
      db.expenses = db.expenses.filter((e) => !(e.trip_id === tripId && e.expense_id === expenseId))
    }),

  getSettlement: (tripId) =>
    respond(() => {
      membership(tripId)
      const bals = balances(
        joinedIds(tripId),
        db.expenses.filter((e) => e.trip_id === tripId),
      )
      return { balances: bals, transfers: settle(bals) }
    }),

  listPacking: (tripId) =>
    respond(() => {
      membership(tripId)
      return db.packing
        .filter((p) => p.trip_id === tripId)
        .map(({ item_id, label, packed, assignee_id }) => ({ item_id, label, packed, assignee_id }))
    }),

  addPacking: (tripId, label, assigneeId) =>
    respond(() => {
      membership(tripId)
      if (!label.trim()) throw new ApiError(400, 'Item needs a name.')
      const item = { item_id: newId('p'), label: label.trim(), packed: false, assignee_id: assigneeId }
      db.packing.push({ ...item, trip_id: tripId })
      return item
    }),

  updatePacking: (tripId, item) =>
    respond(() => {
      membership(tripId)
      const p = db.packing.find((x) => x.trip_id === tripId && x.item_id === item.item_id)
      if (!p) throw new ApiError(404, 'Item not found.')
      Object.assign(p, item)
      return item
    }),

  deletePacking: (tripId, itemId) =>
    respond(() => {
      membership(tripId)
      db.packing = db.packing.filter((p) => !(p.trip_id === tripId && p.item_id === itemId))
    }),
}

function progress(tripId: UUID) {
  const m = membership(tripId)
  const vetoedByMe = new Set(
    db.preferences.filter((p) => p.trip_id === tripId && p.user_id === m.user_id && p.hard_no).map((p) => p.destination_id),
  )
  const eligible = tripDestinations(tripId)
    .map((d: Destination) => d.destination_id)
    .filter((id) => !vetoedByMe.has(id))
  const mine = db.comparisons.filter((c) => c.trip_id === tripId && c.user_id === m.user_id)
  return { done: mine.length, target: PREF_CONFIG.target_comparisons, next: nextPair(eligible, mine) }
}
