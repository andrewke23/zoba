// F07a (point allocation) + F08 (hard no) + destination discovery.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { Category, Destination, Preference, UUID } from '../../api'
import { Badge, Button, Card, ErrorBox, Input, Loading, Notice, PageHeader, ProgressBar } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { CATEGORY_META, formatDuration, hoursSummary, usd } from '../../lib/format'

const STEP = 5

export default function PreferencesPage() {
  const { trip, reload: reloadTrip } = useTrip()
  const navigate = useNavigate()
  const state = useAsync(async () => {
    const [destinations, prefs, cfg] = await Promise.all([
      api.listDestinations(trip.trip_id),
      api.getMyPreferences(trip.trip_id),
      api.getPreferenceConfig(trip.trip_id),
    ])
    return { destinations, prefs, cfg }
  }, [trip.trip_id])

  const [draft, setDraft] = useState<Map<UUID, Preference>>(new Map())
  const [dirty, setDirty] = useState(false)
  const [query, setQuery] = useState('')
  const [cat, setCat] = useState<Category | 'all' | 'mine'>('all')

  useEffect(() => {
    if (state.data) setDraft(new Map(state.data.prefs.map((p) => [p.destination_id, p])))
  }, [state.data])

  const save = useAction(async () => {
    await api.saveMyPreferences(trip.trip_id, [...draft.values()])
    setDirty(false)
    await reloadTrip()
    navigate('../compare')
  })

  const categories = useMemo(() => {
    const set = new Set(state.data?.destinations.map((d) => d.category))
    return (Object.keys(CATEGORY_META) as Category[]).filter((c) => set.has(c))
  }, [state.data])

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!state.data) return <Loading />
  const { destinations, cfg } = state.data

  const get = (id: UUID): Preference => draft.get(id) ?? { destination_id: id, points: 0, rank: null, hard_no: false }
  const used = [...draft.values()].reduce((s, p) => s + (p.hard_no ? 0 : p.points), 0)
  const left = cfg.point_budget - used

  const update = (id: UUID, patch: Partial<Preference>) => {
    setDraft((prev) => {
      const next = new Map(prev)
      next.set(id, { ...get(id), ...patch })
      return next
    })
    setDirty(true)
  }

  const q = query.trim().toLowerCase()
  const visible = destinations.filter((d) => {
    if (cat === 'mine') {
      const p = get(d.destination_id)
      if (!(p.points > 0 || p.hard_no)) return false
    } else if (cat !== 'all' && d.category !== cat) return false
    return !q || d.name.toLowerCase().includes(q) || (d.description ?? '').toLowerCase().includes(q)
  })

  return (
    <div className="pb-28">
      <PageHeader
        title="Where do you want to go?"
        subtitle={`Spend up to ${cfg.point_budget} points on places you're excited about. Mark anything you won't do as a hard no — it'll be left out of the plan.`}
      />
      <Notice>
        Only the first <strong>{cfg.point_cap} points</strong> on any one place count toward its weight, so spreading points around
        gives you more say.
      </Notice>

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input placeholder="Search places…" value={query} onChange={(e) => setQuery(e.target.value)} className="sm:max-w-xs" aria-label="Search places" />
        <div className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
          {(['all', 'mine', ...categories] as const).map((c) => (
            <button
              key={c}
              onClick={() => setCat(c)}
              className={cx(
                'rounded-full border px-3 py-1 text-sm whitespace-nowrap',
                cat === c ? 'border-brand-600 bg-brand-600 text-white' : 'border-stone-300 bg-white text-stone-700 hover:border-stone-400',
              )}
            >
              {c === 'all' ? 'All' : c === 'mine' ? 'My picks' : `${CATEGORY_META[c].emoji} ${CATEGORY_META[c].label}`}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {visible.map((d) => (
          <DestinationCard key={d.destination_id} d={d} pref={get(d.destination_id)} left={left} cap={cfg.point_cap} onChange={(patch) => update(d.destination_id, patch)} />
        ))}
        {visible.length === 0 && <p className="py-8 text-center text-sm text-stone-500 lg:col-span-2">No places match.</p>}
      </div>

      {/* Sticky budget bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-stone-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
          <div className="flex-1">
            <div className="flex justify-between text-sm">
              <span className="font-medium text-stone-900">
                {used} / {cfg.point_budget} points
              </span>
              <span className={cx(left < 0 ? 'text-red-600' : 'text-stone-500')}>{left >= 0 ? `${left} left` : `${-left} over budget`}</span>
            </div>
            <ProgressBar value={used} max={cfg.point_budget} className="mt-1" />
          </div>
          <div className="flex items-center gap-2">
            {save.error && <span className="text-sm text-red-600">{save.error}</span>}
            <Button onClick={() => save.run()} loading={save.pending} disabled={left < 0 || (!dirty && used === 0)}>
              Save & continue →
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function DestinationCard({
  d,
  pref,
  left,
  cap,
  onChange,
}: {
  d: Destination
  pref: Preference
  left: number
  cap: number
  onChange: (patch: Partial<Preference>) => void
}) {
  const meta = CATEGORY_META[d.category]
  return (
    <Card className={cx('flex flex-col p-4 transition-colors', pref.hard_no && 'bg-stone-50 opacity-70', pref.points > 0 && 'border-brand-300')}>
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-xl" aria-hidden>
          {meta.emoji}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className={cx('font-semibold text-stone-900', pref.hard_no && 'line-through')}>{d.name}</h3>
          <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-xs text-stone-500">
            <span>{meta.label}</span>·<span>{d.admission_cost_usd ? usd(d.admission_cost_usd) : 'Free'}</span>·<span>~{formatDuration(d.est_duration_min)}</span>
          </div>
        </div>
        {d.requires_booking && <Badge tone="info">Book ahead</Badge>}
      </div>
      {d.description && <p className="mt-2 text-sm text-stone-600">{d.description}</p>}
      <p className={cx('mt-1 text-xs', d.hours_status === 'ok' ? 'text-stone-400' : 'text-amber-700')}>🕒 {hoursSummary(d)}</p>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-stone-100 pt-3">
        <button
          onClick={() => onChange({ hard_no: !pref.hard_no, points: 0 })}
          className={cx(
            'rounded-lg px-2.5 py-1.5 text-sm font-medium',
            pref.hard_no ? 'bg-red-100 text-red-700' : 'text-stone-500 hover:bg-red-50 hover:text-red-700',
          )}
          aria-pressed={pref.hard_no}
        >
          {pref.hard_no ? '🚫 Hard no' : 'Hard no'}
        </button>
        {!pref.hard_no && (
          <div className="flex items-center gap-1">
            <button
              className="size-8 rounded-lg border border-stone-300 text-lg leading-none text-stone-700 hover:bg-stone-100 disabled:opacity-40"
              onClick={() => onChange({ points: Math.max(0, pref.points - STEP) })}
              disabled={pref.points === 0}
              aria-label={`Fewer points for ${d.name}`}
            >
              −
            </button>
            <span className={cx('w-12 text-center text-sm font-semibold tabular-nums', pref.points > cap ? 'text-amber-700' : 'text-stone-900')} title={pref.points > cap ? `Only ${cap} count toward weight` : undefined}>
              {pref.points}
            </span>
            <button
              className="size-8 rounded-lg border border-brand-300 bg-brand-50 text-lg leading-none text-brand-700 hover:bg-brand-100 disabled:opacity-40"
              onClick={() => onChange({ points: pref.points + Math.min(STEP, left) })}
              disabled={left <= 0}
              aria-label={`More points for ${d.name}`}
            >
              +
            </button>
          </div>
        )}
      </div>
    </Card>
  )
}
