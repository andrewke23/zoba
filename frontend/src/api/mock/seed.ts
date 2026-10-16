
// Demo data for the mock API. Chicago is the placeholder seed city in
// data-pipeline/pipeline/config.py; coordinates are approximate.
import type { City, Destination, Expense, OpeningWindow, PackingItem, Trip, User } from '../types'
import type { MockComparison, MockMembership, MockPreference } from './db'

const h = (hhmm: string) => {
  const [hh, mm] = hhmm.split(':').map(Number)
  return hh * 60 + mm
}

/** Same hours on the given weekdays (0 = Mon). */
function hours(open: string, close: string, days = [0, 1, 2, 3, 4, 5, 6]): OpeningWindow[] {
  let c = h(close)
  if (c <= h(open)) c += 1440
  return days.map((weekday) => ({ weekday, open_min: h(open), close_min: c }))
}

export const SEED_CITIES: City[] = [
  { city_id: 'chicago', name: 'Chicago', center: [-87.6298, 41.8881], timezone: 'America/Chicago' },
  { city_id: 'dc', name: 'Washington, DC', center: [-77.0365, 38.8977], timezone: 'America/New_York' },
]

type D = Omit<Destination, 'city_id' | 'hours_status' | 'address' | 'website' | 'description'> &
  Partial<Pick<Destination, 'hours_status' | 'address' | 'website' | 'description'>>

const chicago: D[] = [
  { destination_id: 'd-art-institute', name: 'Art Institute of Chicago', lat: 41.8796, lng: -87.6237, category: 'museum', admission_cost_usd: 32, est_duration_min: 150, hours: hours('11:00', '17:00', [0, 3, 4, 5, 6]), requires_booking: false, website: 'https://www.artic.edu', description: 'One of the oldest and largest art museums in the US — Seurat, Hopper, the Thorne Miniature Rooms.' },
  { destination_id: 'd-millennium-park', name: 'Millennium Park & Cloud Gate', lat: 41.8826, lng: -87.6226, category: 'landmark', admission_cost_usd: 0, est_duration_min: 45, hours: hours('06:00', '23:00'), requires_booking: false, description: 'Home of "The Bean", Crown Fountain and the Pritzker Pavilion.' },
  { destination_id: 'd-navy-pier', name: 'Navy Pier', lat: 41.8917, lng: -87.6086, category: 'entertainment', admission_cost_usd: 0, est_duration_min: 120, hours: hours('10:00', '22:00'), requires_booking: false, description: 'Lakefront pier with the Centennial Wheel, restaurants and boat tours.' },
  { destination_id: 'd-field-museum', name: 'Field Museum', lat: 41.8663, lng: -87.617, category: 'museum', admission_cost_usd: 30, est_duration_min: 150, hours: hours('09:00', '17:00'), requires_booking: false, website: 'https://www.fieldmuseum.org', description: 'Natural history museum and home to SUE the T. rex.' },
  { destination_id: 'd-shedd', name: 'Shedd Aquarium', lat: 41.8676, lng: -87.614, category: 'entertainment', admission_cost_usd: 45, est_duration_min: 150, hours: hours('09:00', '17:00'), requires_booking: true, website: 'https://www.sheddaquarium.org', description: 'Timed-entry aquarium on Museum Campus. Book ahead on weekends.' },
  { destination_id: 'd-adler', name: 'Adler Planetarium', lat: 41.8663, lng: -87.6068, category: 'museum', admission_cost_usd: 25, est_duration_min: 120, hours: hours('09:30', '16:00'), requires_booking: false, description: "America's first planetarium, with skyline views from Northerly Island." },
  { destination_id: 'd-skydeck', name: 'Skydeck at Willis Tower', lat: 41.8789, lng: -87.6359, category: 'viewpoint', admission_cost_usd: 35, est_duration_min: 60, hours: hours('09:00', '21:00'), requires_booking: true, website: 'https://theskydeck.com', description: 'Glass ledge 103 floors up.' },
  { destination_id: 'd-360', name: '360 Chicago Observation Deck', lat: 41.8989, lng: -87.6229, category: 'viewpoint', admission_cost_usd: 30, est_duration_min: 60, hours: hours('09:00', '23:00'), requires_booking: false, description: 'Observation deck and TILT on the 94th floor of 875 N Michigan.' },
  { destination_id: 'd-lp-zoo', name: 'Lincoln Park Zoo', lat: 41.9211, lng: -87.634, category: 'entertainment', admission_cost_usd: 0, est_duration_min: 120, hours: hours('10:00', '17:00'), requires_booking: false, description: 'Free zoo in Lincoln Park.' },
  { destination_id: 'd-msi', name: 'Museum of Science and Industry', lat: 41.7906, lng: -87.5831, category: 'museum', admission_cost_usd: 26, est_duration_min: 180, hours: hours('09:30', '16:00'), requires_booking: false, description: 'U-505 submarine, coal mine, and a lot of hands-on exhibits. Far south in Hyde Park.' },
  { destination_id: 'd-conservatory', name: 'Garfield Park Conservatory', lat: 41.8863, lng: -87.7173, category: 'park', admission_cost_usd: 0, est_duration_min: 75, hours: hours('10:00', '17:00', [1, 2, 3, 4, 5, 6]), requires_booking: false, description: 'Huge glass-house conservatory on the West Side.' },
  { destination_id: 'd-riverwalk', name: 'Chicago Riverwalk', lat: 41.8879, lng: -87.6268, category: 'park', admission_cost_usd: 0, est_duration_min: 60, hours: hours('06:00', '23:00'), requires_booking: false },
  { destination_id: 'd-arch-cruise', name: 'Architecture River Cruise', lat: 41.8885, lng: -87.6233, category: 'entertainment', admission_cost_usd: 52, est_duration_min: 90, hours: hours('10:00', '19:00'), requires_booking: true, website: 'https://www.architecture.org', description: '90-minute docent-led boat tour of downtown architecture.' },
  { destination_id: 'd-wrigley', name: 'Wrigley Field Tour', lat: 41.9484, lng: -87.6553, category: 'landmark', admission_cost_usd: 35, est_duration_min: 75, hours: hours('10:00', '16:00'), requires_booking: true, description: 'Behind-the-scenes ballpark tour.' },
  { destination_id: 'd-cultural-center', name: 'Chicago Cultural Center', lat: 41.8838, lng: -87.625, category: 'landmark', admission_cost_usd: 0, est_duration_min: 45, hours: hours('10:00', '17:00'), requires_booking: false, description: 'Free landmark with the world\'s largest Tiffany glass dome.' },
  { destination_id: 'd-maggie-daley', name: 'Maggie Daley Park', lat: 41.8825, lng: -87.619, category: 'park', admission_cost_usd: 0, est_duration_min: 45, hours: hours('06:00', '23:00'), requires_booking: false },
  { destination_id: 'd-mag-mile', name: 'Magnificent Mile', lat: 41.8947, lng: -87.6244, category: 'shopping', admission_cost_usd: 0, est_duration_min: 90, hours: hours('10:00', '21:00'), requires_booking: false },
  { destination_id: 'd-lou-malnatis', name: "Lou Malnati's Pizzeria", lat: 41.8902, lng: -87.6339, category: 'food', admission_cost_usd: 25, est_duration_min: 75, hours: hours('11:00', '22:00'), requires_booking: false, description: 'Classic Chicago deep dish.' },
  { destination_id: 'd-pequods', name: "Pequod's Pizza", lat: 41.922, lng: -87.664, category: 'food', admission_cost_usd: 25, est_duration_min: 75, hours: [], hours_status: 'missing', requires_booking: false, description: 'Caramelized-crust pan pizza. (Opening hours unknown in source data.)' },
  { destination_id: 'd-portillos', name: "Portillo's", lat: 41.8935, lng: -87.6283, category: 'food', admission_cost_usd: 15, est_duration_min: 45, hours: hours('10:00', '23:00'), requires_booking: false, description: 'Italian beef and chocolate cake.' },
  { destination_id: 'd-girl-goat', name: 'Girl & the Goat', lat: 41.8841, lng: -87.648, category: 'food', admission_cost_usd: 60, est_duration_min: 90, hours: hours('17:00', '22:00'), requires_booking: true, description: 'West Loop small plates. Reservations go fast.' },
  { destination_id: 'd-intelligentsia', name: 'Intelligentsia Coffee', lat: 41.8842, lng: -87.6252, category: 'cafe', admission_cost_usd: 6, est_duration_min: 30, hours: hours('06:30', '19:00'), requires_booking: false },
  { destination_id: 'd-second-city', name: 'The Second City', lat: 41.9116, lng: -87.6354, category: 'entertainment', admission_cost_usd: 45, est_duration_min: 120, hours: hours('19:00', '23:30'), hours_status: 'partial', requires_booking: true, description: 'Legendary improv comedy theatre.' },
  { destination_id: 'd-green-mill', name: 'Green Mill Cocktail Lounge', lat: 41.969, lng: -87.6597, category: 'nightlife', admission_cost_usd: 15, est_duration_min: 90, hours: hours('12:00', '02:00'), requires_booking: false, description: 'Historic Uptown jazz club.' },
]

export const SEED_DESTINATIONS: Destination[] = chicago.map((d) => ({
  city_id: 'chicago',
  address: null,
  website: null,
  description: null,
  hours_status: 'ok',
  ...d,
}))

export const DEMO_PASSWORD = 'zoba'

export const SEED_USERS: User[] = [
  { user_id: 'u-demo', email: 'demo@zoba.app', display_name: 'Demo Organizer' },
  { user_id: 'u-maya', email: 'maya@zoba.app', display_name: 'Maya' },
  { user_id: 'u-jordan', email: 'jordan@zoba.app', display_name: 'Jordan' },
  { user_id: 'u-sam', email: 'sam@zoba.app', display_name: 'Sam' },
]

export const SEED_TRIP: Trip = {
  trip_id: 't-chicago',
  name: 'Chicago Fall Weekend',
  organizer_id: 'u-demo',
  city_id: 'chicago',
  start_date: '2026-11-06',
  end_date: '2026-11-08',
  day_start: '09:00',
  day_end: '21:00',
  home_base: { label: 'Hotel — 151 E Wacker Dr', lat: 41.8881, lng: -87.6229 },
  invite_token: 'chi-fall-26',
  created_at: '2026-10-01T15:00:00Z',
}

export const SEED_MEMBERSHIPS: MockMembership[] = [
  { trip_id: 't-chicago', user_id: 'u-demo', role: 'organizer', status: 'joined' },
  { trip_id: 't-chicago', user_id: 'u-maya', role: 'member', status: 'joined' },
  { trip_id: 't-chicago', user_id: 'u-jordan', role: 'member', status: 'joined' },
  { trip_id: 't-chicago', user_id: 'u-sam', role: 'member', status: 'joined' },
]

// Distinct tastes so the fairness-aware ranking has something to balance.
const tastes: Record<string, { points: Record<string, number>; hardNo?: string[]; likes: string[] }> = {
  'u-maya': {
    points: { 'd-art-institute': 40, 'd-arch-cruise': 25, 'd-girl-goat': 20, 'd-cultural-center': 15 },
    hardNo: ['d-wrigley'],
    likes: ['d-art-institute', 'd-arch-cruise', 'd-girl-goat', 'd-cultural-center', 'd-millennium-park', 'd-riverwalk', 'd-conservatory'],
  },
  'u-jordan': {
    points: { 'd-wrigley': 35, 'd-lou-malnatis': 25, 'd-skydeck': 25, 'd-navy-pier': 15 },
    likes: ['d-wrigley', 'd-lou-malnatis', 'd-skydeck', 'd-navy-pier', 'd-portillos', 'd-360', 'd-green-mill'],
  },
  'u-sam': {
    points: { 'd-shedd': 45, 'd-field-museum': 30, 'd-adler': 25 },
    hardNo: ['d-green-mill'],
    likes: ['d-shedd', 'd-field-museum', 'd-adler', 'd-msi', 'd-lp-zoo', 'd-millennium-park', 'd-maggie-daley'],
  },
}

export function seedPreferences(): MockPreference[] {
  const out: MockPreference[] = []
  for (const [user_id, t] of Object.entries(tastes)) {
    for (const [destination_id, points] of Object.entries(t.points)) {
      out.push({ trip_id: 't-chicago', user_id, destination_id, points, rank: null, hard_no: false })
    }
    for (const destination_id of t.hardNo ?? []) {
      out.push({ trip_id: 't-chicago', user_id, destination_id, points: 0, rank: null, hard_no: true })
    }
  }
  return out
}

export function seedComparisons(): MockComparison[] {
  const out: MockComparison[] = []
  const ids = SEED_DESTINATIONS.map((d) => d.destination_id)
  let ts = Date.parse('2026-10-05T12:00:00Z')
  for (const [user_id, t] of Object.entries(tastes)) {
    const liked = new Set(t.likes)
    // Deterministic pairs: each liked place beats a couple of non-liked ones,
    // and earlier "likes" beat later ones.
    const others = ids.filter((id) => !liked.has(id) && !(t.hardNo ?? []).includes(id))
    t.likes.forEach((a, i) => {
      for (let k = 0; k < 2; k++) {
        const b = others[(i * 3 + k * 5 + user_id.length) % others.length]
        out.push({ trip_id: 't-chicago', user_id, dest_a: a, dest_b: b, chosen: a, created_at: new Date((ts += 60000)).toISOString() })
      }
      if (i + 1 < t.likes.length) {
        const b = t.likes[i + 1]
        out.push({ trip_id: 't-chicago', user_id, dest_a: b, dest_b: a, chosen: a, created_at: new Date((ts += 60000)).toISOString() })
      }
    })
  }
  return out
}

export const SEED_EXPENSES: Expense[] = [
  {
    expense_id: 'e-hotel',
    trip_id: 't-chicago',
    payer_id: 'u-maya',
    amount_cents: 64000,
    description: 'Hotel deposit (2 nights)',
    created_at: '2026-10-08T18:00:00Z',
    shares: SEED_MEMBERSHIPS.map((m) => ({ user_id: m.user_id, share_cents: 16000 })),
  },
  {
    expense_id: 'e-train',
    trip_id: 't-chicago',
    payer_id: 'u-jordan',
    amount_cents: 9000,
    description: 'Amtrak tickets (Jordan, Sam, Maya)',
    created_at: '2026-10-09T18:00:00Z',
    shares: ['u-jordan', 'u-sam', 'u-maya'].map((user_id) => ({ user_id, share_cents: 3000 })),
  },
]

export const SEED_PACKING: (PackingItem & { trip_id: string })[] = [
  { trip_id: 't-chicago', item_id: 'p-1', label: 'Warm jacket (November lakefront wind)', packed: false, assignee_id: null },
  { trip_id: 't-chicago', item_id: 'p-2', label: 'Portable phone charger', packed: false, assignee_id: 'u-jordan' },
  { trip_id: 't-chicago', item_id: 'p-3', label: 'Ventra transit card', packed: true, assignee_id: null },
]
