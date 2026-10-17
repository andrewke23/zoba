// Client-side stand-ins for backend algorithms so the mock behaves realistically.
// The real implementations live in the FastAPI service (NumPy/SciPy, OR-Tools);
// these only need to be plausible, not optimal.
import type {
  Balance,
  ComparisonPair,
  Destination,
  ExpenseInput,
  ISODate,
  ItineraryDay,
  ItineraryStop,
  LockRequest,
  PreferenceConfig,
  RankingRow,
  SolverKind,
  Transfer,
  TravelMode,
  Trip,
  UUID,
} from '../types'
import type { MockComparison, MockPreference } from './db'

export const PREF_CONFIG: PreferenceConfig = { point_budget: 100, point_cap: 40, target_comparisons: 15 }

// ---------------------------------------------------------------------------
// Bradley–Terry (F04)
// ---------------------------------------------------------------------------

/** MM-algorithm fit (Hunter 2004) with a weak prior so unseen items stay finite. Returns log-strengths. */
export function bradleyTerry(ids: UUID[], comps: { a: UUID; b: UUID; winner: UUID }[], iters = 60): Map<UUID, number> {
  const idx = new Map(ids.map((id, i) => [id, i]))
  const n = ids.length
  const wins = new Array<number>(n).fill(0.5) // prior: half a win…
  const pairs = new Map<string, number>()
  const key = (i: number, j: number) => (i < j ? `${i}:${j}` : `${j}:${i}`)
  for (const c of comps) {
    const i = idx.get(c.a)
    const j = idx.get(c.b)
    const w = idx.get(c.winner)
    if (i === undefined || j === undefined || w === undefined) continue
    wins[w] += 1
    pairs.set(key(i, j), (pairs.get(key(i, j)) ?? 0) + 1)
  }
  let p = new Array<number>(n).fill(1)
  for (let it = 0; it < iters; it++) {
    const next = new Array<number>(n)
    for (let i = 0; i < n; i++) {
      let denom = 1 / (p[i] + 1) // …and one comparison against a virtual average item
      for (const [k, cnt] of pairs) {
        const [a, b] = k.split(':').map(Number)
        if (a === i) denom += cnt / (p[i] + p[b])
        else if (b === i) denom += cnt / (p[i] + p[a])
      }
      next[i] = wins[i] / denom
    }
    const mean = next.reduce((s, x) => s + x, 0) / n
    p = next.map((x) => x / mean)
  }
  return new Map(ids.map((id, i) => [id, Math.log(p[i])]))
}

function minMax(values: Map<UUID, number>): Map<UUID, number> {
  const xs = [...values.values()]
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  return new Map([...values].map(([k, v]) => [k, hi - lo < 1e-9 ? 0.5 : (v - lo) / (hi - lo)]))
}

/** Pick the most informative next pair: close in current estimate, under-compared, not repeated. */
export function nextPair(eligible: UUID[], comps: MockComparison[]): ComparisonPair | null {
  if (eligible.length < 2) return null
  const theta = bradleyTerry(
    eligible,
    comps.map((c) => ({ a: c.dest_a, b: c.dest_b, winner: c.chosen })),
  )
  const seen = new Map<UUID, number>()
  const pairCount = new Map<string, number>()
  for (const c of comps) {
    seen.set(c.dest_a, (seen.get(c.dest_a) ?? 0) + 1)
    seen.set(c.dest_b, (seen.get(c.dest_b) ?? 0) + 1)
    const k = [c.dest_a, c.dest_b].sort().join('|')
    pairCount.set(k, (pairCount.get(k) ?? 0) + 1)
  }
  let best: ComparisonPair | null = null
  let bestCost = Infinity
  for (let i = 0; i < eligible.length; i++) {
    for (let j = i + 1; j < eligible.length; j++) {
      const a = eligible[i]
      const b = eligible[j]
      const k = [a, b].sort().join('|')
      const cost =
        Math.abs(theta.get(a)! - theta.get(b)!) +
        0.35 * ((seen.get(a) ?? 0) + (seen.get(b) ?? 0)) +
        10 * (pairCount.get(k) ?? 0) +
        // tiny deterministic jitter so ties don't always pick the same corner
        ((a.charCodeAt(2) * 31 + b.charCodeAt(2) * 17 + comps.length * 7) % 13) / 100
      if (cost < bestCost) {
        bestCost = cost
        best = comps.length % 2 ? { dest_a: b, dest_b: a } : { dest_a: a, dest_b: b }
      }
    }
  }
  return best
}

// ---------------------------------------------------------------------------
// Group ranking (F06, F08, F08a)
// ---------------------------------------------------------------------------

export interface RankingResult {
  rows: RankingRow[]
  /** user_id → destination_id → normalized utility 0..1 */
  utility: Map<UUID, Map<UUID, number>>
  vetoed: Set<UUID>
  topPicks: Map<UUID, UUID | null>
}

export function computeRanking(
  destinations: Destination[],
  memberIds: UUID[],
  prefs: MockPreference[],
  comps: MockComparison[],
  cfg: PreferenceConfig = PREF_CONFIG,
): RankingResult {
  const ids = destinations.map((d) => d.destination_id)
  const vetoed = new Set(prefs.filter((p) => p.hard_no).map((p) => p.destination_id))
  const utility = new Map<UUID, Map<UUID, number>>()
  const active: UUID[] = []

  for (const uid of memberIds) {
    const myPrefs = prefs.filter((p) => p.user_id === uid)
    const myComps = comps.filter((c) => c.user_id === uid)
    if (!myPrefs.some((p) => p.points > 0) && myComps.length === 0) continue
    active.push(uid)
    const bt = minMax(bradleyTerry(ids, myComps.map((c) => ({ a: c.dest_a, b: c.dest_b, winner: c.chosen }))))
    const raw = new Map<UUID, number>()
    for (const id of ids) {
      const pts = myPrefs.find((p) => p.destination_id === id)?.points ?? 0
      const pointsWeight = Math.min(pts, cfg.point_cap) / cfg.point_cap
      raw.set(id, 0.6 * (myComps.length ? bt.get(id)! : 0.5) + 0.4 * pointsWeight)
    }
    // Per-member normalization: someone who did 40 comparisons doesn't outweigh someone who did 10.
    utility.set(uid, minMax(raw))
  }

  const capTotal = prefs.reduce((s, p) => s + Math.min(p.points, cfg.point_cap), 0) || 1
  const rows: RankingRow[] = ids.map((id) => {
    const us = active.map((uid) => utility.get(uid)!.get(id)!)
    const mean = us.length ? us.reduce((s, x) => s + x, 0) / us.length : 0
    const min = us.length ? Math.min(...us) : 0
    const forDest = prefs.filter((p) => p.destination_id === id)
    return {
      destination_id: id,
      rank: 0,
      raw_points: forDest.reduce((s, p) => s + p.points, 0),
      raw_votes: forDest.filter((p) => p.points > 0).length,
      weighted_points: forDest.reduce((s, p) => s + Math.min(p.points, cfg.point_cap), 0) / capTotal,
      // Fairness-aware: blend average happiness with the least-happy member.
      group_score: vetoed.has(id) ? 0 : 0.5 * mean + 0.5 * min,
      min_member_utility: min,
      vetoed_by: prefs.filter((p) => p.hard_no && p.destination_id === id).map((p) => p.user_id),
    }
  })
  rows.sort((a, b) => Number(a.vetoed_by.length > 0) - Number(b.vetoed_by.length > 0) || b.group_score - a.group_score)
  rows.forEach((r, i) => (r.rank = i + 1))

  const topPicks = new Map<UUID, UUID | null>()
  for (const uid of memberIds) {
    const u = utility.get(uid)
    if (!u) {
      topPicks.set(uid, null)
      continue
    }
    let best: UUID | null = null
    for (const id of ids) if (!vetoed.has(id) && (best === null || u.get(id)! > u.get(best)!)) best = id
    topPicks.set(uid, best)
  }
  return { rows, utility, vetoed, topPicks }
}

// ---------------------------------------------------------------------------
// Travel + time helpers
// ---------------------------------------------------------------------------

interface Pt {
  lat: number
  lng: number
}

export function haversineKm(a: Pt, b: Pt): number {
  const R = 6371
  const rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad
  const dLng = (b.lng - a.lng) * rad
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(s))
}

/** Stand-in for the cached OSRM/OTP matrix. */
export function travel(a: Pt, b: Pt): { min: number; mode: TravelMode } {
  const km = haversineKm(a, b) * 1.3 // street-network detour factor
  if (km <= 1.6) return { min: Math.max(3, Math.ceil((km / 4.8) * 60)), mode: 'walk' }
  return { min: Math.ceil((km / 18) * 60) + 8, mode: 'transit' }
}

export const toMin = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}
const pad = (n: number) => String(n).padStart(2, '0')
export const fromMin = (m: number) => `${pad(Math.floor(m / 60) % 24)}:${pad(m % 60)}`
/** Local trip time, no offset. Backend should send an offset form; the UI only reads the HH:MM part. */
export const ts = (date: ISODate, min: number) => `${date}T${fromMin(min)}:00`
export const tsToMin = (s: string) => toMin(s.slice(11, 16))

export function tripDates(trip: Trip): ISODate[] {
  const out: ISODate[] = []
  const d = new Date(`${trip.start_date}T00:00:00Z`)
  const end = new Date(`${trip.end_date}T00:00:00Z`)
  while (d <= end) {
    out.push(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

/** 0 = Mon … 6 = Sun */
export const weekdayOf = (date: ISODate) => (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7

function hoursKnown(d: Destination) {
  return d.hours.length > 0 && (d.hours_status === 'ok' || d.hours_status === 'partial')
}

/** Earliest start ≥ t such that [start, start+dur] fits an opening window; null if none. */
function earliestOpenStart(d: Destination, date: ISODate, t: number, dur: number): number | null {
  if (!hoursKnown(d)) return t
  const wd = weekdayOf(date)
  let best: number | null = null
  for (const w of d.hours) {
    if (w.weekday !== wd) continue
    const s = Math.max(t, w.open_min)
    if (s + dur <= w.close_min && (best === null || s < best)) best = s
  }
  return best
}

export function isOpenDuring(d: Destination, date: ISODate, start: number, end: number): boolean {
  if (!hoursKnown(d)) return true
  const wd = weekdayOf(date)
  return d.hours.some((w) => w.weekday === wd && w.open_min <= start && end <= w.close_min)
}

// ---------------------------------------------------------------------------
// Scheduling (F07, F09–F12)
// ---------------------------------------------------------------------------

export interface ScheduleInput {
  trip: Trip
  destinations: Map<UUID, Destination>
  /** Eligible (non-vetoed) destinations in priority order, with their group score */
  candidates: { id: UUID; score: number }[]
  mustInclude: UUID[]
  locks: (LockRequest & { destination_id: UUID })[]
  solver: SolverKind
}

export interface ScheduleOutput {
  days: ItineraryDay[]
  conflicts: string[]
  unplaced: Map<UUID, string>
}

const MAX_FOOD_PER_DAY = 2
const MAX_WAIT_MIN = 60

export function schedule(input: ScheduleInput): ScheduleOutput {
  const { trip, destinations, solver } = input
  const dates = tripDates(trip)
  const dayStart = toMin(trip.day_start)
  const dayEnd = toMin(trip.day_end)
  const home: Pt = trip.home_base
  const conflicts: string[] = []
  const unplaced = new Map<UUID, string>()
  const lockedIds = new Set(input.locks.map((l) => l.destination_id))

  const must = new Set(input.mustInclude.filter((id) => !lockedIds.has(id)))
  const remaining = input.candidates.filter((c) => !lockedIds.has(c.id))
  // Top picks first (F07), then by score.
  remaining.sort((a, b) => Number(must.has(b.id)) - Number(must.has(a.id)) || b.score - a.score)

  // Validate locks up front.
  const locksByDay = new Map<number, { id: UUID; start: number; end: number }[]>()
  for (const l of input.locks) {
    const d = destinations.get(l.destination_id)
    if (!d) continue
    if (l.day_index < 0 || l.day_index >= dates.length) {
      conflicts.push(`${d.name} is locked to a day outside the trip dates and was dropped.`)
      continue
    }
    const start = tsToMin(l.start_ts)
    const end = start + d.est_duration_min
    const date = dates[l.day_index]
    if (start < dayStart || end > dayEnd) conflicts.push(`${d.name} is locked outside the daily window (${trip.day_start}–${trip.day_end}).`)
    if (!isOpenDuring(d, date, start, end)) conflicts.push(`${d.name} is locked at a time it isn't open (Day ${l.day_index + 1}).`)
    const list = locksByDay.get(l.day_index) ?? []
    for (const o of list) {
      if (start < o.end && o.start < end) conflicts.push(`${d.name} overlaps another locked stop on Day ${l.day_index + 1}.`)
    }
    list.push({ id: l.destination_id, start, end })
    locksByDay.set(l.day_index, list)
  }

  const days: ItineraryDay[] = dates.map((date, dayIdx) => {
    const fixed = (locksByDay.get(dayIdx) ?? []).sort((a, b) => a.start - b.start)
    const stops: ItineraryStop[] = []
    let cur = dayStart
    let pos: Pt = home
    let food = 0
    let lastWasFood = false

    const push = (id: UUID, start: number, end: number, tr: { min: number; mode: TravelMode }, locked: boolean) => {
      const d = destinations.get(id)!
      stops.push({
        trip_id: trip.trip_id,
        day_index: dayIdx,
        seq: stops.length,
        destination_id: id,
        start_ts: ts(date, start),
        end_ts: ts(date, end),
        locked,
        travel_min_from_prev: tr.min,
        travel_mode_from_prev: tr.mode,
      })
      cur = end
      pos = d
      lastWasFood = d.category === 'food'
      if (lastWasFood) food++
    }

    let fi = 0
    for (;;) {
      const nextFixed = fixed[fi]
      let best: { idx: number; start: number; tr: { min: number; mode: TravelMode }; value: number } | null = null
      for (let i = 0; i < remaining.length; i++) {
        const d = destinations.get(remaining[i].id)!
        if (d.category === 'food' && (food >= MAX_FOOD_PER_DAY || lastWasFood)) continue
        const tr = travel(pos, d)
        const arrive = cur + tr.min
        const start = earliestOpenStart(d, date, arrive, d.est_duration_min)
        if (start === null || start - arrive > MAX_WAIT_MIN) continue
        const end = start + d.est_duration_min
        if (end > dayEnd) continue
        if (nextFixed) {
          const fd = destinations.get(nextFixed.id)!
          if (end + travel(d, fd).min > nextFixed.start) continue
        }
        if (solver === 'greedy') {
          // First feasible in priority order.
          best = { idx: i, start, tr, value: 0 }
          break
        }
        // "cpsat" stand-in: weigh score against time lost to travel and waiting.
        const prio = must.has(remaining[i].id) ? 10 : 0
        const value = prio + remaining[i].score / (1 + tr.min / 30 + (start - arrive) / 60)
        if (!best || value > best.value) best = { idx: i, start, tr, value }
      }
      if (best) {
        const [c] = remaining.splice(best.idx, 1)
        push(c.id, best.start, best.start + destinations.get(c.id)!.est_duration_min, best.tr, false)
        continue
      }
      if (nextFixed) {
        const fd = destinations.get(nextFixed.id)!
        const tr = travel(pos, fd)
        if (cur + tr.min > nextFixed.start) {
          conflicts.push(`Not enough travel time to reach locked stop ${fd.name} on Day ${dayIdx + 1}.`)
        }
        push(nextFixed.id, nextFixed.start, nextFixed.end, tr, true)
        fi++
        continue
      }
      break
    }
    return { day_index: dayIdx, date, stops }
  })

  for (const c of remaining) {
    const d = destinations.get(c.id)!
    const openAnyDay = dates.some((date) => earliestOpenStart(d, date, dayStart, d.est_duration_min) !== null)
    unplaced.set(
      c.id,
      !openAnyDay
        ? 'Closed (or too short a window) on every trip day'
        : d.est_duration_min > dayEnd - dayStart
          ? 'Visit is longer than the daily window'
          : 'Did not fit — higher-scoring stops filled the days',
    )
  }
  return { days, conflicts, unplaced }
}

// ---------------------------------------------------------------------------
// Expenses (F17)
// ---------------------------------------------------------------------------

export function balances(memberIds: UUID[], expenses: ExpenseInput[]): Balance[] {
  const map = new Map<UUID, Balance>(memberIds.map((id) => [id, { user_id: id, paid_cents: 0, owed_cents: 0, net_cents: 0 }]))
  const get = (id: UUID) => {
    if (!map.has(id)) map.set(id, { user_id: id, paid_cents: 0, owed_cents: 0, net_cents: 0 })
    return map.get(id)!
  }
  for (const e of expenses) {
    get(e.payer_id).paid_cents += e.amount_cents
    for (const s of e.shares) get(s.user_id).owed_cents += s.share_cents
  }
  for (const b of map.values()) b.net_cents = b.paid_cents - b.owed_cents
  return [...map.values()]
}

/** Greedy largest-creditor ↔ largest-debtor matching; at most n−1 transfers. */
export function settle(bals: Balance[]): Transfer[] {
  const cred = bals.filter((b) => b.net_cents > 0).map((b) => ({ id: b.user_id, amt: b.net_cents }))
  const debt = bals.filter((b) => b.net_cents < 0).map((b) => ({ id: b.user_id, amt: -b.net_cents }))
  const out: Transfer[] = []
  while (cred.length && debt.length) {
    cred.sort((a, b) => b.amt - a.amt)
    debt.sort((a, b) => b.amt - a.amt)
    const c = cred[0]
    const d = debt[0]
    const amt = Math.min(c.amt, d.amt)
    out.push({ from_user_id: d.id, to_user_id: c.id, amount_cents: amt })
    c.amt -= amt
    d.amt -= amt
    if (c.amt === 0) cred.shift()
    if (d.amt === 0) debt.shift()
  }
  return out
}
