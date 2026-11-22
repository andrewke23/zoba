// Hybrid mode (the default): trip places come from the backend, and the
// mock-served voting pages run against those real places.
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

describe('hybrid destinations', () => {
  it('runs in hybrid mode by default', () => {
    expect(API_MODE).toBe('hybrid')
  })

  it('loads a trip’s places from the backend', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(LONDON), { status: 200 }))
    expect(await realApi.listDestinations!('trip-a')).toEqual(LONDON)
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/trips/trip-a/destinations')
  })

  it('gives the mock voting pages the real places for any city', async () => {
    mirrorLondonTrip('trip-b')
    // Before: the demo catalog has no London places.
    expect(await mockApi.listDestinations('trip-b')).toEqual([])

    spyRealDestinations().mockResolvedValue(LONDON)
    expect(await api.listDestinations('trip-b')).toEqual(LONDON)
    expect((await mockApi.listDestinations('trip-b')).map((d) => d.name)).toEqual(['British Museum', 'Tate Modern', 'Hyde Park'])
  })

  it('syncs places before comparisons, so pairs use real place IDs', async () => {
    mirrorLondonTrip('trip-c')
    spyRealDestinations().mockResolvedValue(LONDON)

    const progress = await api.getComparisonProgress('trip-c')
    const ids = LONDON.map((d) => d.destination_id)
    expect(progress.next).not.toBeNull()
    expect(ids).toContain(progress.next!.dest_a)
    expect(ids).toContain(progress.next!.dest_b)
  })

  it('saves preferences for real places', async () => {
    mirrorLondonTrip('trip-d')
    spyRealDestinations().mockResolvedValue(LONDON)

    await api.saveMyPreferences('trip-d', [{ destination_id: 'lon-1', points: 60, rank: null, hard_no: false }])
    expect(await api.getMyPreferences('trip-d')).toEqual([expect.objectContaining({ destination_id: 'lon-1', points: 60 })])
  })

  it('fetches a trip’s places once per page load', async () => {
    mirrorLondonTrip('trip-e')
    const list = spyRealDestinations().mockResolvedValue(LONDON)
    await api.listDestinations('trip-e')
    await api.getComparisonProgress('trip-e')
    await api.getGroupResults('trip-e')
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
