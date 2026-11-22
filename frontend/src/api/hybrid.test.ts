// Hybrid mode (the default): voting, tasks and packing go to the backend; the
// one mock-served method (correctDuration) runs against the backend's places.
import { describe, expect, it, vi } from 'vitest'
import { API_MODE, api } from '.'
import { realApi } from './http'
import { hybridBridge, mockApi } from './mock'
import { ApiError } from './types'
import type { Destination, Member, Trip, User } from './types'

const user: User = { user_id: 'u-lon', email: 'lon@example.com', display_name: 'Lauren' }

const londonPlace = (id: string, name: string): Destination => ({
  destination_id: id,
  city_id: 'london',
  name,
  lat: 51.5,
  lng: -0.12,
  category: 'museum',
  address: null,
  website: null,
  description: null,
  admission_cost_usd: null,
  est_duration_min: 120,
  hours: [],
  hours_status: 'missing',
  requires_booking: false,
})

/** realApi is Partial<ZobaApi>; narrow it so vi.spyOn can type the method. */
const spyRealDestinations = () => vi.spyOn(realApi as Required<typeof realApi>, 'listDestinations')

const LONDON = [londonPlace('lon-1', 'British Museum'), londonPlace('lon-2', 'Tate Modern'), londonPlace('lon-3', 'Hyde Park')]

/** Put a real London trip (and me as its organizer) into the mock, as TripLayout would. */
function mirrorLondonTrip(tripId: string) {
  const trip: Trip = {
    trip_id: tripId,
    name: 'London',
    organizer_id: user.user_id,
    city_id: 'london',
    start_date: '2026-12-10',
    end_date: '2026-12-12',
    day_start: '09:00',
    day_end: '21:00',
    home_base: { label: 'Hotel', lat: 51.5, lng: -0.12 },
    invite_token: 'tok',
    created_at: '2026-11-22T00:00:00Z',
  }
  const me: Member = { ...user, role: 'organizer', status: 'joined', preferences_submitted: false, comparisons_done: 0 }
  hybridBridge.signIn(user)
  hybridBridge.trip(trip)
  hybridBridge.members(tripId, [me])
}

describe('hybrid mode', () => {
  it('runs in hybrid mode by default', () => {
    expect(API_MODE).toBe('hybrid')
  })

  it('loads a trip’s places from the backend', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(LONDON), { status: 200 }))
    expect(await realApi.listDestinations!('trip-a')).toEqual(LONDON)
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/trips/trip-a/destinations')
  })

  it('gives the mock the real places for any city', async () => {
    mirrorLondonTrip('trip-b')
    // Before: the demo catalog has no London places.
    expect(await mockApi.listDestinations('trip-b')).toEqual([])

    spyRealDestinations().mockResolvedValue(LONDON)
    expect(await api.listDestinations('trip-b')).toEqual(LONDON)
    expect((await mockApi.listDestinations('trip-b')).map((d) => d.name)).toEqual(['British Museum', 'Tate Modern', 'Hyde Park'])
  })

  it('sends voting, tasks and packing to the backend', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(null, { status: 204 }))
    const prefs = [{ destination_id: 'lon-1', points: 60, rank: null, hard_no: false }]

    await api.saveMyPreferences('trip-c', prefs)
    await api.getComparisonProgress('trip-c')
    await api.submitComparison('trip-c', { dest_a: 'lon-1', dest_b: 'lon-2' }, 'lon-2')
    await api.getGroupResults('trip-c')
    await api.getPreferenceConfig('trip-c')
    await api.listTasks('trip-c')
    await api.listPacking('trip-c')

    const calls = fetchSpy.mock.calls.map(([url, init]) => `${init?.method} ${url}`)
    expect(calls).toEqual([
      'PUT /api/v1/trips/trip-c/preferences/me',
      'GET /api/v1/trips/trip-c/comparisons/progress',
      'POST /api/v1/trips/trip-c/comparisons',
      'GET /api/v1/trips/trip-c/group-results',
      'GET /api/v1/trips/trip-c/preference-config',
      'GET /api/v1/trips/trip-c/tasks',
      'GET /api/v1/trips/trip-c/packing',
    ])
    expect(JSON.parse(fetchSpy.mock.calls[0][1]!.body as string)).toEqual(prefs)
    expect(JSON.parse(fetchSpy.mock.calls[2][1]!.body as string)).toEqual({ dest_a: 'lon-1', dest_b: 'lon-2', chosen: 'lon-2' })
  })

  it('reads voting progress from the backend member list', async () => {
    const member: Member = { ...user, role: 'organizer', status: 'joined', preferences_submitted: true, comparisons_done: 4 }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([member]), { status: 200 }))
    expect(await api.listMembers('trip-d')).toEqual([member])
  })

  it('corrects a duration on a real place', async () => {
    mirrorLondonTrip('trip-h')
    spyRealDestinations().mockResolvedValue(LONDON)

    const updated = await api.correctDuration('trip-h', 'lon-1', 90)
    expect(updated.destination_id).toBe('lon-1')
  })

  it('fetches a trip’s places once per page load', async () => {
    mirrorLondonTrip('trip-e')
    const list = spyRealDestinations().mockResolvedValue(LONDON)
    await api.listDestinations('trip-e')
    await api.correctDuration('trip-e', 'lon-1', 90)
    await api.correctDuration('trip-e', 'lon-2', 45)
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('retries after a failed fetch instead of caching the error', async () => {
    mirrorLondonTrip('trip-f')
    const list = spyRealDestinations()
      .mockRejectedValueOnce(new ApiError(503, 'Backend down'))
      .mockResolvedValue(LONDON)

    await expect(api.listDestinations('trip-f')).rejects.toThrow('Backend down')
    expect(await api.listDestinations('trip-f')).toEqual(LONDON)
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('keeps other cities’ places when syncing one city', async () => {
    mirrorLondonTrip('trip-g')
    spyRealDestinations().mockResolvedValue(LONDON)
    await api.listDestinations('trip-g')
    // The demo Chicago catalog is untouched.
    hybridBridge.trip({ ...(await mockApi.getTrip('trip-g')), trip_id: 'trip-chi', city_id: 'chicago' })
    hybridBridge.members('trip-chi', [{ ...user, role: 'organizer', status: 'joined', preferences_submitted: false, comparisons_done: 0 }])
    expect((await mockApi.listDestinations('trip-chi')).length).toBeGreaterThan(0)
  })
})
