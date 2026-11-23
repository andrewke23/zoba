import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api'
import { city, itinerary, ME, otherCity, prefConfig, tasks, trip, tripSummaries } from '../test/fixtures'
import { renderPage } from '../test/render'
import NewTripPage from './NewTripPage'
import TripsPage from './TripsPage'
import OverviewPage from './trip/OverviewPage'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: ME }) }))
// jsdom has no WebGL: make the map fail so TripForm shows its fallback text.
vi.mock('maplibre-gl', () => ({
  default: {
    Map: class {
      constructor() {
        throw new Error('WebGL unavailable')
      }
    },
    Marker: class {},
  },
}))

describe('TripsPage (my trips)', () => {
  it('lists each trip with its city, role and traveler count', async () => {
    vi.spyOn(api, 'listTrips').mockResolvedValue(tripSummaries)
    renderPage(<TripsPage />, { ctx: false })

    const chicago = (await screen.findByText('Chicago weekend')).closest('a')!
    expect(chicago).toHaveAttribute('href', '/trips/t1')
    expect(within(chicago).getByText('Organizer')).toBeInTheDocument()
    expect(within(chicago).getByText('3 travelers')).toBeInTheDocument()
    expect(within(chicago).getByText(/Chicago · Dec 4 – Dec 5, 2026/)).toBeInTheDocument()

    const nyc = screen.getByText('NYC solo').closest('a')!
    expect(within(nyc).getByText('Member')).toBeInTheDocument()
    expect(within(nyc).getByText('1 traveler')).toBeInTheDocument()
  })

  it('shows an empty state when there are no trips', async () => {
    vi.spyOn(api, 'listTrips').mockResolvedValue([])
    renderPage(<TripsPage />, { ctx: false })
    expect(await screen.findByText('No trips yet')).toBeInTheDocument()
  })

  it('shows an error with a retry button that refetches', async () => {
    const list = vi.spyOn(api, 'listTrips').mockRejectedValueOnce(new ApiError(500, 'Server is down')).mockResolvedValue(tripSummaries)
    const user = userEvent.setup()
    renderPage(<TripsPage />, { ctx: false })

    expect(await screen.findByRole('alert')).toHaveTextContent('Server is down')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Chicago weekend')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('links to the new-trip page', async () => {
    vi.spyOn(api, 'listTrips').mockResolvedValue([])
    renderPage(<TripsPage />, { ctx: false })
    expect((await screen.findByRole('button', { name: '+ New trip' })).closest('a')).toHaveAttribute('href', '/trips/new')
  })
})

describe('NewTripPage (trip form)', () => {
  beforeEach(() => {
    vi.spyOn(api, 'listCities').mockResolvedValue([city, otherCity])
  })

  async function fillForm(user: ReturnType<typeof userEvent.setup>) {
    await user.type(await screen.findByLabelText('Trip name'), 'Chicago weekend')
    fireEvent.change(screen.getByLabelText('Start date'), { target: { value: '2026-12-04' } })
    fireEvent.change(screen.getByLabelText('End date'), { target: { value: '2026-12-05' } })
    await user.type(screen.getByPlaceholderText(/Hotel or address/), 'Hotel Wacker')
  }

  it('creates the trip with the form values and opens its settings', async () => {
    const create = vi.spyOn(api, 'createTrip').mockResolvedValue(trip)
    const user = userEvent.setup()
    renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create trip' }))

    expect(create).toHaveBeenCalledWith({
      name: 'Chicago weekend',
      city_id: 'chicago',
      start_date: '2026-12-04',
      end_date: '2026-12-05',
      day_start: '09:00',
      day_end: '21:00',
      home_base: { label: 'Hotel Wacker', lat: 41.88, lng: -87.63 },
    })
    expect(await screen.findByTestId('navigated')).toHaveTextContent('/trips/t1/settings')
  })

  it('moves the home base to the new city center when the city changes', async () => {
    const create = vi.spyOn(api, 'createTrip').mockResolvedValue(trip)
    const user = userEvent.setup()
    renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    await fillForm(user)
    await user.selectOptions(screen.getByLabelText(/^City/), 'nyc')
    expect(screen.getByText('40.71000, -74.00000')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Create trip' }))
    expect(create.mock.calls[0][0]).toMatchObject({ city_id: 'nyc', home_base: { lat: 40.71, lng: -74.0 } })
  })

  it('rejects an end date before the start date', async () => {
    const create = vi.spyOn(api, 'createTrip')
    const user = userEvent.setup()
    const { container } = renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    await fillForm(user)
    fireEvent.change(screen.getByLabelText('End date'), { target: { value: '2026-12-01' } })
    // Submit directly: the browser's own min= check would stop a real click first.
    fireEvent.submit(container.querySelector('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent('End date must be on or after the start date.')
    expect(create).not.toHaveBeenCalled()
  })

  it('rejects a daily end time that is not after the start time', async () => {
    const create = vi.spyOn(api, 'createTrip')
    const user = userEvent.setup()
    const { container } = renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    await fillForm(user)
    fireEvent.change(screen.getByLabelText('Day ends'), { target: { value: '08:00' } })
    fireEvent.submit(container.querySelector('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent('Daily end time must be after the start time.')
    expect(create).not.toHaveBeenCalled()
  })

  it('shows the server error and stays on the form', async () => {
    vi.spyOn(api, 'createTrip').mockRejectedValue(new ApiError(422, 'name: String should have at most 120 characters'))
    const user = userEvent.setup()
    renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create trip' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('name: String should have at most 120 characters')
    expect(screen.queryByTestId('navigated')).not.toBeInTheDocument()
  })

  it('falls back gracefully when the map cannot load', async () => {
    renderPage(<NewTripPage />, { path: '/trips/new', ctx: false })
    expect(await screen.findByText(/Map unavailable/)).toBeInTheDocument()
  })
})

describe('OverviewPage (trip home)', () => {
  function mockOverview({ withItinerary }: { withItinerary: boolean }) {
    vi.spyOn(api, 'getPreferenceConfig').mockResolvedValue(prefConfig)
    vi.spyOn(api, 'getItinerary').mockResolvedValue(withItinerary ? itinerary : null)
    vi.spyOn(api, 'listTasks').mockResolvedValue(tasks)
  }

  it('shows the trip header and each traveler’s progress', async () => {
    mockOverview({ withItinerary: false })
    renderPage(<OverviewPage />, { path: '/trips/t1' })

    expect(await screen.findByRole('heading', { name: 'Chicago weekend' })).toBeInTheDocument()
    expect(screen.getByText(/Chicago · Dec 4 – Dec 5, 2026 · 9:00 AM–9:00 PM daily · from Hotel Wacker/)).toBeInTheDocument()
    expect(screen.getByText('3 travelers')).toBeInTheDocument()
    expect(screen.getByText('(you)')).toBeInTheDocument()
    expect(screen.getByText('10/10 comparisons')).toBeInTheDocument()
    expect(screen.getByText('Points in')).toBeInTheDocument()
    expect(screen.getAllByText('No points yet')).toHaveLength(2)
  })

  it('tells the organizer to generate when there is no itinerary yet', async () => {
    mockOverview({ withItinerary: false })
    renderPage(<OverviewPage />, { path: '/trips/t1' })
    expect(await screen.findByText('Once everyone has voted, generate the itinerary.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generate →' })).toHaveAttribute('href', '/trips/t1/itinerary')
    expect(screen.getByRole('link', { name: 'Invite' })).toBeInTheDocument()
  })

  it('sends members to the results page instead, and hides Invite', async () => {
    mockOverview({ withItinerary: false })
    renderPage(<OverviewPage />, { path: '/trips/t1', ctx: { isOrganizer: false, myRole: 'member' } })
    expect(await screen.findByText('The organizer will generate the itinerary once everyone has voted.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'See results →' })).toHaveAttribute('href', '/trips/t1/results')
    expect(screen.queryByRole('link', { name: 'Invite' })).not.toBeInTheDocument()
  })

  it('summarizes the itinerary and open tasks once a plan exists', async () => {
    mockOverview({ withItinerary: true })
    renderPage(<OverviewPage />, { path: '/trips/t1' })
    expect(await screen.findByText('3 stops across 2 days.')).toBeInTheDocument()
    expect(screen.getByText(/1 open task\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View →' })).toBeInTheDocument()
  })

  it('shows the load error', async () => {
    vi.spyOn(api, 'getPreferenceConfig').mockRejectedValue(new ApiError(403, 'You are not a member of this trip'))
    vi.spyOn(api, 'getItinerary').mockResolvedValue(null)
    vi.spyOn(api, 'listTasks').mockResolvedValue([])
    renderPage(<OverviewPage />, { path: '/trips/t1' })
    expect(await screen.findByRole('alert')).toHaveTextContent('You are not a member of this trip')
  })
})
