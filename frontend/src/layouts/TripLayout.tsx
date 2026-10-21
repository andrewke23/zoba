import { useCallback, useMemo } from 'react'
import { Link, NavLink, Outlet, useParams } from 'react-router-dom'
import { api, syncHybridTrip } from '../api'
import type { UUID } from '../api'
import { useAuth } from '../auth/AuthContext'
import { Badge, ErrorBox, Loading } from '../components/ui'
import { cx } from '../lib/cx'
import { useAsync } from '../hooks/useAsync'
import { formatDateRange } from '../lib/format'
import { TripContext } from './TripContext'
import type { TripCtx } from './TripContext'

interface NavItem {
  to: string
  label: string
  icon: string
  organizerOnly?: boolean
}

const NAV: { section: string; items: NavItem[] }[] = [
  { section: '', items: [{ to: '', label: 'Overview', icon: '🏠' }] },
  {
    section: 'Decide',
    items: [
      { to: 'preferences', label: 'Preferences', icon: '⭐' },
      { to: 'compare', label: 'This or that', icon: '⚖️' },
      { to: 'results', label: 'Group results', icon: '📊' },
    ],
  },
  { section: 'Plan', items: [{ to: 'itinerary', label: 'Itinerary', icon: '🗺️' }] },
  {
    section: 'Prepare',
    items: [
      { to: 'tasks', label: 'Tasks', icon: '✅' },
      { to: 'budget', label: 'Costs & expenses', icon: '💸' },
      { to: 'packing', label: 'Packing list', icon: '🎒' },
    ],
  },
  {
    section: 'Organizer',
    items: [
      { to: 'settings', label: 'Trip settings', icon: '⚙️', organizerOnly: true },
      { to: 'solvers', label: 'Compare solvers', icon: '🧪', organizerOnly: true },
    ],
  },
]

export default function TripLayout() {
  const { tripId = '' } = useParams()
  const { user } = useAuth()

  const state = useAsync(async () => {
    const [trip, members, cities] = await Promise.all([api.getTrip(tripId), api.listMembers(tripId), api.listCities()])
    syncHybridTrip(trip, members, cities.find((city) => city.city_id === trip.city_id))
    return { trip, members, cities }
  }, [tripId])
  const { data, error, reload } = state

  const memberName = useCallback(
    (id: UUID) => data?.members.find((m) => m.user_id === id)?.display_name ?? 'Former member',
    [data],
  )

  const ctx = useMemo<TripCtx | null>(() => {
    if (!data || !user) return null
    const me = data.members.find((m) => m.user_id === user.user_id)
    const myRole = me?.role ?? 'member'
    return {
      trip: data.trip,
      city: data.cities.find((c) => c.city_id === data.trip.city_id),
      members: data.members.filter((m) => m.status === 'joined'),
      myRole,
      isOrganizer: myRole === 'organizer',
      memberName,
      reload,
    }
  }, [data, user, memberName, reload])

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <ErrorBox error={error} onRetry={reload} />
        <Link to="/" className="mt-4 inline-block text-sm font-medium text-brand-700">
          ← Back to my trips
        </Link>
      </div>
    )
  }
  if (!ctx) return <Loading />

  const items = NAV.map((s) => ({ ...s, items: s.items.filter((i) => !i.organizerOnly || ctx.isOrganizer) })).filter((s) => s.items.length)
  const linkCls = ({ isActive }: { isActive: boolean }) =>
    cx(
      'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
      isActive ? 'bg-brand-50 text-brand-800' : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900',
    )

  return (
    <TripContext.Provider value={ctx}>
      <div className="mx-auto max-w-6xl px-4 pt-4 pb-16">
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link to="/" className="text-sm text-stone-500 hover:text-stone-800">
            My trips
          </Link>
          <span className="text-stone-300">/</span>
          <h2 className="font-semibold text-stone-900">{ctx.trip.name}</h2>
          <span className="text-sm text-stone-500">
            {ctx.city?.name} · {formatDateRange(ctx.trip.start_date, ctx.trip.end_date)}
          </span>
          {ctx.isOrganizer && <Badge tone="brand">Organizer</Badge>}
        </div>

        <div className="md:flex md:gap-6">
          {/* Mobile: horizontal scroll tabs. Desktop: sidebar. */}
          <nav aria-label="Trip sections" className="sticky top-14 z-20 -mx-4 mb-4 border-b border-stone-200 bg-stone-50/95 px-4 backdrop-blur md:hidden">
            <div className="no-scrollbar flex gap-1 overflow-x-auto py-2">
              {items.flatMap((s) => s.items).map((i) => (
                <NavLink key={i.to} to={i.to} end={i.to === ''} className={linkCls}>
                  <span aria-hidden>{i.icon}</span>
                  {i.label}
                </NavLink>
              ))}
            </div>
          </nav>
          <nav aria-label="Trip sections" className="sticky top-20 hidden h-fit w-52 shrink-0 md:block">
            {items.map((s) => (
              <div key={s.section} className="mb-4">
                {s.section && <div className="mb-1 px-3 text-xs font-semibold tracking-wide text-stone-400 uppercase">{s.section}</div>}
                <div className="flex flex-col gap-0.5">
                  {s.items.map((i) => (
                    <NavLink key={i.to} to={i.to} end={i.to === ''} className={linkCls}>
                      <span aria-hidden>{i.icon}</span>
                      {i.label}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <div className="min-w-0 flex-1">
            <Outlet />
          </div>
        </div>
      </div>
    </TripContext.Provider>
  )
}
