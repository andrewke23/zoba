import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../../api'
import type { Itinerary } from '../../api'
import { destinations, itinerary } from '../../test/fixtures'
import { renderPage } from '../../test/render'
import ItineraryPage from './ItineraryPage'

// The real map needs WebGL; the stub just reports what it was asked to show.
vi.mock('../../components/TripMap', () => ({
  default: ({ selectedDay, days }: { selectedDay: number | null; days: unknown[] }) => (
    <div data-testid="map">
      map: {days.length} days, selected {selectedDay === null ? 'all' : selectedDay}
    </div>
  ),
}))

function mockItinerary(it: Itinerary | null = itinerary) {
  vi.spyOn(api, 'getItinerary').mockResolvedValue(it)
  vi.spyOn(api, 'listDestinations').mockResolvedValue(destinations)
}

const renderItinerary = (organizer = true) =>
  renderPage(<ItineraryPage />, { path: '/trips/t1/itinerary', ctx: organizer ? {} : { isOrganizer: false, myRole: 'member' } })

const stopEl = (container: HTMLElement, id: string) => container.querySelector<HTMLElement>(`#stop-${id}`)!

/** A copy of the fixture itinerary with one stop changed. */
function withStop(destId: string, change: Partial<Itinerary['days'][0]['stops'][0]>): Itinerary {
  return {
    ...itinerary,
    days: itinerary.days.map((d) => ({ ...d, stops: d.stops.map((s) => (s.destination_id === destId ? { ...s, ...change } : s)) })),
  }
}

describe('ItineraryPage — before generating', () => {
  it('lets the organizer pick a method and generate', async () => {
    mockItinerary(null)
    const generate = vi.spyOn(api, 'generateItinerary').mockResolvedValue(itinerary)
    const user = userEvent.setup()
    renderItinerary()

    expect(await screen.findByText('No itinerary yet')).toBeInTheDocument()
    expect(screen.getByLabelText('Scheduling method')).toHaveValue('cpsat')
    await user.selectOptions(screen.getByLabelText('Scheduling method'), 'greedy')
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    expect(generate).toHaveBeenCalledWith('t1', 'greedy')
    expect(await screen.findByRole('heading', { name: 'Day 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '↻ Regenerate' })).toBeInTheDocument()
  })

  it('tells members to wait and hides the generate controls', async () => {
    mockItinerary(null)
    renderItinerary(false)
    expect(await screen.findByText(/The organizer hasn't generated the itinerary yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument()
  })

  it('shows the error when generating fails', async () => {
    mockItinerary(null)
    vi.spyOn(api, 'generateItinerary').mockRejectedValue(new ApiError(409, 'Nobody has voted yet'))
    const user = userEvent.setup()
    renderItinerary()
    await user.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nobody has voted yet')
  })

  it('shows the load error', async () => {
    vi.spyOn(api, 'getItinerary').mockRejectedValue(new ApiError(500, 'Itinerary unavailable'))
    vi.spyOn(api, 'listDestinations').mockResolvedValue(destinations)
    renderItinerary()
    expect(await screen.findByRole('alert')).toHaveTextContent('Itinerary unavailable')
  })
})

describe('ItineraryPage — viewing the plan', () => {
  it('shows each day with its stops in order, with times and travel', async () => {
    mockItinerary()
    const { container } = renderItinerary()
    expect(await screen.findByRole('heading', { name: 'Day 1' })).toBeInTheDocument()
    expect(screen.getByText('Friday, December 4')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Day 2' })).toBeInTheDocument()
    expect(screen.getAllByText('🏨 Start at Hotel Wacker')).toHaveLength(2)

    const art = stopEl(container, 'd1')
    expect(art).toHaveTextContent('10:00 AM – 11:30 AM')
    expect(art).toHaveTextContent('🏛️ Art Institute')
    expect(art).toHaveTextContent('🚶 12 min walk')
    expect(art).toHaveTextContent('Daily 10:00 AM–5:00 PM')
    expect(within(art).getByText('Book ahead')).toBeInTheDocument()
    expect(within(art).getByRole('link', { name: 'Website ↗' })).toHaveAttribute('href', 'https://artic.edu')

    const park = stopEl(container, 'd2')
    expect(park).toHaveTextContent('🚇 12 min transit')
    expect(within(park).getByText('🔒 Locked')).toBeInTheDocument()
    expect(within(park).getAllByText('Hours unknown').length).toBeGreaterThan(0)
  })

  it('shows the solver and locked count in the subtitle', async () => {
    mockItinerary()
    renderItinerary()
    expect(await screen.findByText(/Optimized \(OR-Tools\) · 1 locked/)).toBeInTheDocument()
  })

  it('filters to one day with the day chips', async () => {
    mockItinerary()
    const user = userEvent.setup()
    renderItinerary()
    await user.click(await screen.findByRole('button', { name: /Day 2 · Sat, Dec 5/ }))

    expect(screen.queryByRole('heading', { name: 'Day 1' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Day 2' })).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveTextContent('selected 1')

    await user.click(screen.getByRole('button', { name: 'All days' }))
    expect(screen.getByRole('heading', { name: 'Day 1' })).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveTextContent('selected all')
  })

  it("shows whether each traveler's top pick made it in", async () => {
    mockItinerary()
    renderItinerary()
    // heading → CardHeader → Card
    const card = (await screen.findByRole('heading', { name: "Everyone's top pick" })).closest('div')!.parentElement!.parentElement!
    const [ana, ben, cy] = within(card).getAllByRole('listitem')
    expect(ana).toHaveTextContent(/Ana — Art Institute\s*Included/)
    expect(ben).toHaveTextContent(/Ben — Skydeck\s*Did not fit/)
    expect(cy).toHaveTextContent(/Cy — no input\s*Not included/)
  })

  it('lists places left out and why', async () => {
    mockItinerary()
    renderItinerary()
    expect(await screen.findByText('Not in the plan')).toBeInTheDocument()
    expect(screen.getByText('Closed during the trip window')).toBeInTheDocument()
  })

  it('warns about conflicts', async () => {
    mockItinerary({ ...itinerary, conflicts: ['Navy Pier is closed at the locked time.'] })
    renderItinerary()
    expect(await screen.findByText('Heads up')).toBeInTheDocument()
    expect(screen.getByText('Navy Pier is closed at the locked time.')).toBeInTheDocument()
  })

  it('shows a free day when a day has no stops', async () => {
    mockItinerary({ ...itinerary, days: [itinerary.days[0], { ...itinerary.days[1], stops: [] }] })
    renderItinerary()
    expect(await screen.findByText(/Free day/)).toBeInTheDocument()
  })

  it('regenerates with the chosen method', async () => {
    mockItinerary()
    const generate = vi.spyOn(api, 'generateItinerary').mockResolvedValue({ ...itinerary, solver: 'greedy' })
    const user = userEvent.setup()
    renderItinerary()
    await user.click(await screen.findByRole('button', { name: '↻ Regenerate' }))
    expect(generate).toHaveBeenCalledWith('t1', 'cpsat')
    expect(await screen.findByText(/Fast \(greedy\)/, { selector: 'p' })).toBeInTheDocument()
  })

  it('hides regenerate from members', async () => {
    mockItinerary()
    renderItinerary(false)
    await screen.findByRole('heading', { name: 'Day 1' })
    expect(screen.queryByRole('button', { name: '↻ Regenerate' })).not.toBeInTheDocument()
  })
})

describe('ItineraryPage — locking and durations', () => {
  it('locks a stop to a chosen day and time', async () => {
    mockItinerary()
    const lock = vi.spyOn(api, 'setStopLock').mockResolvedValue(withStop('d1', { locked: true }))
    const user = userEvent.setup()
    const { container } = renderItinerary()
    await screen.findByRole('heading', { name: 'Day 1' })
    await user.click(within(stopEl(container, 'd1')).getByRole('button', { name: '🔒 Lock' }))

    const dialog = screen.getByRole('dialog', { name: 'Lock Art Institute' })
    // Prefilled from the stop's current slot.
    expect(within(dialog).getByLabelText('Day')).toHaveValue('0')
    expect(within(dialog).getByLabelText('Start time')).toHaveValue('10:00')

    await user.selectOptions(within(dialog).getByLabelText('Day'), '1')
    await user.clear(within(dialog).getByLabelText('Start time'))
    await user.type(within(dialog).getByLabelText('Start time'), '15:30')
    await user.click(within(dialog).getByRole('button', { name: 'Lock & rebuild' }))

    expect(lock).toHaveBeenCalledWith('t1', 'd1', { day_index: 1, start_ts: '2026-12-05T15:30:00' })
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(within(stopEl(container, 'd1')).getByText('🔒 Locked')).toBeInTheDocument()
  })

  it('keeps the lock dialog open when the stop cannot fit', async () => {
    mockItinerary()
    vi.spyOn(api, 'setStopLock').mockRejectedValue(new ApiError(409, 'Art Institute is closed then'))
    const user = userEvent.setup()
    const { container } = renderItinerary()
    await screen.findByRole('heading', { name: 'Day 1' })
    await user.click(within(stopEl(container, 'd1')).getByRole('button', { name: '🔒 Lock' }))
    await user.click(screen.getByRole('button', { name: 'Lock & rebuild' }))

    const dialog = screen.getByRole('dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Art Institute is closed then')
  })

  it('unlocks a locked stop', async () => {
    mockItinerary()
    const lock = vi.spyOn(api, 'setStopLock').mockResolvedValue(withStop('d2', { locked: false }))
    const user = userEvent.setup()
    const { container } = renderItinerary()
    await screen.findByRole('heading', { name: 'Day 1' })
    await user.click(within(stopEl(container, 'd2')).getByRole('button', { name: 'Unlock' }))

    expect(lock).toHaveBeenCalledWith('t1', 'd2', null)
    expect(await within(stopEl(container, 'd2')).findByRole('button', { name: '🔒 Lock' })).toBeInTheDocument()
  })

  it('saves a duration correction and shows the new estimate', async () => {
    mockItinerary()
    const correct = vi.spyOn(api, 'correctDuration').mockResolvedValue({ ...destinations[0], est_duration_min: 120 })
    const user = userEvent.setup()
    const { container } = renderItinerary()
    await screen.findByRole('heading', { name: 'Day 1' })
    await user.click(within(stopEl(container, 'd1')).getByRole('button', { name: '⏱ 1 h 30 min' }))

    const dialog = screen.getByRole('dialog', { name: 'How long does this take?' })
    expect(within(dialog).getByLabelText('Minutes')).toHaveValue(90)
    await user.clear(within(dialog).getByLabelText('Minutes'))
    await user.type(within(dialog).getByLabelText('Minutes'), '120')
    await user.click(within(dialog).getByRole('button', { name: 'Save correction' }))

    expect(correct).toHaveBeenCalledWith('t1', 'd1', 120)
    expect(await within(stopEl(container, 'd1')).findByRole('button', { name: '⏱ 2 h' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
