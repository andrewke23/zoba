// Small, consistent sample data for page tests: one Chicago trip, three travelers.
import type {
  City,
  CostEstimate,
  Destination,
  Expense,
  Itinerary,
  ItineraryStop,
  Member,
  PreferenceConfig,
  Settlement,
  Task,
  Trip,
  TripSummary,
  User,
} from '../api/types'

export const ME: User = { user_id: 'u-ana', email: 'ana@example.com', display_name: 'Ana' }

export const city: City = { city_id: 'chicago', name: 'Chicago', center: [-87.63, 41.88], timezone: 'America/Chicago' }
export const otherCity: City = { city_id: 'nyc', name: 'New York', center: [-74.0, 40.71], timezone: 'America/New_York' }

export const trip: Trip = {
  trip_id: 't1',
  name: 'Chicago weekend',
  organizer_id: ME.user_id,
  city_id: 'chicago',
  start_date: '2026-12-04',
  end_date: '2026-12-05',
  day_start: '09:00',
  day_end: '21:00',
  home_base: { label: 'Hotel Wacker', lat: 41.88, lng: -87.62 },
  invite_token: 'inv-1',
  created_at: '2026-11-01T00:00:00Z',
}

const member = (user_id: string, display_name: string, extra: Partial<Member> = {}): Member => ({
  user_id,
  email: `${display_name.toLowerCase()}@example.com`,
  display_name,
  role: 'member',
  status: 'joined',
  preferences_submitted: false,
  comparisons_done: 0,
  ...extra,
})

export const members: Member[] = [
  member('u-ana', 'Ana', { role: 'organizer', preferences_submitted: true, comparisons_done: 10 }),
  member('u-ben', 'Ben', { comparisons_done: 4 }),
  member('u-cy', 'Cy'),
]

export const memberName = (id: string) => members.find((m) => m.user_id === id)?.display_name ?? 'Former member'

export const tripSummaries: TripSummary[] = [
  { ...trip, city_name: 'Chicago', my_role: 'organizer', member_count: 3 },
  { ...trip, trip_id: 't2', name: 'NYC solo', city_id: 'nyc', city_name: 'New York', my_role: 'member', member_count: 1 },
]

export const prefConfig: PreferenceConfig = { point_budget: 100, point_cap: 40, target_comparisons: 10 }

export const tasks: Task[] = [
  { task_id: 'k1', trip_id: 't1', title: 'Book museum', due_date: null, status: 'open', destination_id: 'd1', auto_generated: true, booking_url: null },
]

// ---- Itinerary ----

const dest = (destination_id: string, name: string, extra: Partial<Destination> = {}): Destination => ({
  destination_id,
  city_id: 'chicago',
  name,
  lat: 41.88,
  lng: -87.62,
  category: 'museum',
  address: null,
  website: null,
  description: null,
  admission_cost_usd: null,
  est_duration_min: 90,
  hours: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({ weekday, open_min: 600, close_min: 1020 })),
  hours_status: 'ok',
  requires_booking: false,
  ...extra,
})

export const destinations: Destination[] = [
  dest('d1', 'Art Institute', { requires_booking: true, website: 'https://artic.edu' }),
  dest('d2', 'Millennium Park', { category: 'park', est_duration_min: 45, hours_status: 'missing', hours: [] }),
  dest('d3', 'Navy Pier', { category: 'entertainment' }),
  dest('d4', 'Skydeck', { category: 'viewpoint' }),
]

const stop = (destination_id: string, day_index: number, date: string, start: string, end: string, extra: Partial<ItineraryStop> = {}): ItineraryStop => ({
  trip_id: 't1',
  day_index,
  seq: 0,
  destination_id,
  start_ts: `${date}T${start}:00`,
  end_ts: `${date}T${end}:00`,
  locked: false,
  travel_min_from_prev: 12,
  travel_mode_from_prev: 'walk',
  ...extra,
})

export const itinerary: Itinerary = {
  trip_id: 't1',
  solver: 'cpsat',
  generated_at: '2026-11-20T15:00:00Z',
  days: [
    {
      day_index: 0,
      date: '2026-12-04',
      stops: [stop('d1', 0, '2026-12-04', '10:00', '11:30'), stop('d2', 0, '2026-12-04', '12:00', '12:45', { locked: true, travel_mode_from_prev: 'transit' })],
    },
    { day_index: 1, date: '2026-12-05', stops: [stop('d3', 1, '2026-12-05', '13:00', '14:30')] },
  ],
  unscheduled: [{ destination_id: 'd4', reason: 'Closed during the trip window' }],
  top_picks: [
    { user_id: 'u-ana', destination_id: 'd1', included: true, reason: null },
    { user_id: 'u-ben', destination_id: 'd4', included: false, reason: 'Did not fit' },
    { user_id: 'u-cy', destination_id: null, included: false, reason: null },
  ],
  conflicts: [],
  metrics: { solver: 'cpsat', runtime_ms: 120, group_score: 0.8, min_member_utility: 0.5, stops_scheduled: 3, travel_min_total: 40, feasible: true },
}

// ---- Budget ----

export const estimate: CostEstimate = {
  per_member: [
    { user_id: 'u-ana', admission_usd: 40, transport_usd: 12.5, meals_usd: 60, total_usd: 112.5 },
    { user_id: 'u-ben', admission_usd: 40, transport_usd: 12.5, meals_usd: 60, total_usd: 112.5 },
  ],
  assumptions: ['Transit is estimated at CTA fares.'],
}

export const expenses: Expense[] = [
  {
    expense_id: 'e1',
    trip_id: 't1',
    payer_id: 'u-ana',
    amount_cents: 9000,
    description: 'Dinner',
    created_at: '2026-12-04T20:00:00Z',
    shares: [
      { user_id: 'u-ana', share_cents: 3000 },
      { user_id: 'u-ben', share_cents: 3000 },
      { user_id: 'u-cy', share_cents: 3000 },
    ],
  },
]

export const settlement: Settlement = {
  balances: [
    { user_id: 'u-ana', paid_cents: 9000, owed_cents: 3000, net_cents: 6000 },
    { user_id: 'u-ben', paid_cents: 0, owed_cents: 3000, net_cents: -3000 },
    { user_id: 'u-cy', paid_cents: 0, owed_cents: 3000, net_cents: -3000 },
  ],
  transfers: [
    { from_user_id: 'u-ben', to_user_id: 'u-ana', amount_cents: 3000 },
    { from_user_id: 'u-cy', to_user_id: 'u-ana', amount_cents: 3000 },
  ],
}
