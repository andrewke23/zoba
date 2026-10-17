import type { Category, Destination, ISODate, TravelMode } from '../api'

export const CATEGORY_META: Record<Category, { label: string; emoji: string }> = {
  museum: { label: 'Museum', emoji: '🏛️' },
  landmark: { label: 'Landmark', emoji: '📍' },
  park: { label: 'Park', emoji: '🌳' },
  viewpoint: { label: 'Viewpoint', emoji: '🏙️' },
  entertainment: { label: 'Entertainment', emoji: '🎟️' },
  food: { label: 'Food', emoji: '🍽️' },
  cafe: { label: 'Café', emoji: '☕' },
  nightlife: { label: 'Nightlife', emoji: '🎷' },
  shopping: { label: 'Shopping', emoji: '🛍️' },
  other: { label: 'Other', emoji: '✨' },
}

export const MODE_META: Record<TravelMode, { label: string; emoji: string }> = {
  walk: { label: 'Walk', emoji: '🚶' },
  transit: { label: 'Transit', emoji: '🚇' },
  drive: { label: 'Drive', emoji: '🚗' },
}

/** Distinct, colorblind-friendlier day colors used on the map and timeline. */
export const DAY_COLORS = ['#256c69', '#e07b24', '#6d5bd0', '#c2416b', '#2f7fc1', '#7a8c1e', '#a15c2f', '#4b5563']
export const dayColor = (i: number) => DAY_COLORS[i % DAY_COLORS.length]

export function usd(n: number, digits = 0) {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export const cents = (c: number) => usd(c / 100, 2)

export function formatDate(d: ISODate, opts: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' }) {
  return new Date(`${d}T12:00:00`).toLocaleDateString('en-US', opts)
}

export function formatDateRange(a: ISODate, b: ISODate) {
  const sameYear = a.slice(0, 4) === b.slice(0, 4)
  const left = formatDate(a, { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) })
  const right = formatDate(b, { month: 'short', day: 'numeric', year: 'numeric' })
  return a === b ? right : `${left} – ${right}`
}

/** "13:30" → "1:30 PM" */
export function formatTime(hhmm: string) {
  const [h, m] = hhmm.split(':').map(Number)
  const suffix = h >= 12 && h < 24 ? 'PM' : 'AM'
  const hh = h % 12 === 0 ? 12 : h % 12
  return `${hh}:${String(m).padStart(2, '0')} ${suffix}`
}

/** Reads the local HH:MM out of an ISO timestamp (trip-local time). */
export const timeOf = (ts: string) => formatTime(ts.slice(11, 16))

export function formatDuration(min: number) {
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function hoursSummary(d: Destination): string {
  if (d.hours_status === 'missing' || d.hours_status === 'unparseable' || d.hours.length === 0) return 'Hours unknown'
  const byDay = WEEKDAYS.map((_, i) => d.hours.filter((w) => w.weekday === i))
  const fmt = (m: number) => formatTime(`${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`)
  const label = (ws: typeof d.hours) => (ws.length ? ws.map((w) => `${fmt(w.open_min)}–${fmt(w.close_min)}`).join(', ') : 'Closed')
  const labels = byDay.map(label)
  if (labels.every((l) => l === labels[0])) return `Daily ${labels[0]}`
  const closed = WEEKDAYS.filter((_, i) => labels[i] === 'Closed')
  const open = labels.find((l) => l !== 'Closed')!
  if (labels.filter((l) => l !== 'Closed').every((l) => l === open)) return `${open} · closed ${closed.join(', ')}`
  return WEEKDAYS.map((w, i) => `${w} ${labels[i]}`).join('; ')
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

export const pct = (x: number) => `${Math.round(x * 100)}%`
