import { Link } from 'react-router-dom'
import { api } from '../../api'
import { useAuth } from '../../auth/AuthContext'
import { Avatar, Badge, Card, CardHeader, ErrorBox, Loading, PageHeader, ProgressBar } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { formatDateRange, formatTime } from '../../lib/format'

export default function OverviewPage() {
  const { trip, city, members, isOrganizer } = useTrip()
  const { user } = useAuth()
  const state = useAsync(async () => {
    const [cfg, itinerary, tasks] = await Promise.all([api.getPreferenceConfig(trip.trip_id), api.getItinerary(trip.trip_id), api.listTasks(trip.trip_id)])
    return { cfg, itinerary, tasks }
  }, [trip.trip_id])

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!state.data) return <Loading />
  const { cfg, itinerary, tasks } = state.data
  const me = members.find((m) => m.user_id === user?.user_id)
  const openTasks = tasks.filter((t) => t.status === 'open').length

  const steps = [
    {
      done: !!me?.preferences_submitted,
      title: 'Share your preferences',
      body: `Spend ${cfg.point_budget} points on the places you want to go and mark any hard no's.`,
      to: 'preferences',
      cta: me?.preferences_submitted ? 'Edit' : 'Start',
    },
    {
      done: (me?.comparisons_done ?? 0) >= cfg.target_comparisons,
      title: 'Play this-or-that',
      body: `Pick between two places at a time. ${me?.comparisons_done ?? 0} / ${cfg.target_comparisons} done.`,
      to: 'compare',
      cta: 'Compare',
    },
    {
      done: !!itinerary,
      title: 'Review the plan',
      body: itinerary
        ? `${itinerary.days.reduce((s, d) => s + d.stops.length, 0)} stops across ${itinerary.days.length} days.`
        : isOrganizer
          ? 'Once everyone has voted, generate the itinerary.'
          : 'The organizer will generate the itinerary once everyone has voted.',
      to: itinerary || isOrganizer ? 'itinerary' : 'results',
      cta: itinerary ? 'View' : isOrganizer ? 'Generate' : 'See results',
    },
    {
      done: !!itinerary && openTasks === 0,
      title: 'Get ready',
      body: itinerary ? `${openTasks} open task${openTasks === 1 ? '' : 's'}. Track costs and split expenses.` : 'Booking tasks and cost estimates appear once there is a plan.',
      to: 'tasks',
      cta: 'Tasks',
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title={trip.name}
        subtitle={`${city?.name ?? trip.city_id} · ${formatDateRange(trip.start_date, trip.end_date)} · ${formatTime(trip.day_start)}–${formatTime(trip.day_end)} daily · from ${trip.home_base.label}`}
      />

      <Card>
        <CardHeader title="Your next steps" />
        <ol className="divide-y divide-stone-100">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-center gap-4 px-4 py-3">
              <span
                className={cx(
                  'flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold',
                  s.done ? 'bg-emerald-100 text-emerald-700' : 'bg-stone-100 text-stone-500',
                )}
              >
                {s.done ? '✓' : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-medium text-stone-900">{s.title}</div>
                <div className="text-sm text-stone-600">{s.body}</div>
              </div>
              <Link to={s.to} className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-50">
                {s.cta} →
              </Link>
            </li>
          ))}
        </ol>
      </Card>

      <Card>
        <CardHeader title="Group progress" subtitle={`${members.length} traveler${members.length === 1 ? '' : 's'}`} action={isOrganizer ? <Link to="settings" className="text-sm font-medium text-brand-700">Invite</Link> : undefined} />
        <ul className="divide-y divide-stone-100">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center gap-3 px-4 py-3">
              <Avatar name={m.display_name} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-stone-900">
                  {m.display_name}
                  {m.user_id === user?.user_id && <span className="text-stone-400">(you)</span>}
                  {m.role === 'organizer' && <Badge tone="brand">Organizer</Badge>}
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <ProgressBar value={Math.min(m.comparisons_done, cfg.target_comparisons)} max={cfg.target_comparisons} className="max-w-40" />
                  <span className="text-xs text-stone-500">
                    {m.comparisons_done}/{cfg.target_comparisons} comparisons
                  </span>
                </div>
              </div>
              {m.preferences_submitted ? <Badge tone="success">Points in</Badge> : <Badge tone="warn">No points yet</Badge>}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
