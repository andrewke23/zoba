// F09–F14: generate, view (map + timeline), lock, regenerate, correct durations.
import { useCallback, useMemo, useState } from 'react'
import { api } from '../../api'
import type { Destination, Itinerary, ItineraryStop, SolverKind, UUID } from '../../api'
import TripMap from '../../components/TripMap'
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, ErrorBox, Field, Input, Loading, Modal, Notice, PageHeader, Select } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { CATEGORY_META, MODE_META, dayColor, formatDate, formatDuration, hoursSummary, timeOf } from '../../lib/format'

const SOLVER_LABEL: Record<SolverKind, string> = { greedy: 'Fast (greedy)', cpsat: 'Optimized (OR-Tools)' }

export default function ItineraryPage() {
  const { trip, isOrganizer, memberName } = useTrip()
  const state = useAsync(async () => {
    const [itinerary, destinations] = await Promise.all([api.getItinerary(trip.trip_id), api.listDestinations(trip.trip_id)])
    return { itinerary, destinations: new Map(destinations.map((d) => [d.destination_id, d])) }
  }, [trip.trip_id])
  const { data, setData } = state

  const [solver, setSolver] = useState<SolverKind>('cpsat')
  const [day, setDay] = useState<number | null>(null)
  const [highlighted, setHighlighted] = useState<UUID | null>(null)
  const [lockTarget, setLockTarget] = useState<ItineraryStop | null>(null)
  const [durationTarget, setDurationTarget] = useState<ItineraryStop | null>(null)

  const setItinerary = useCallback((it: Itinerary) => data && setData({ ...data, itinerary: it }), [data, setData])

  const generate = useAction(async () => setItinerary(await api.generateItinerary(trip.trip_id, solver)))
  const unlock = useAction(async (destId: UUID) => setItinerary(await api.setStopLock(trip.trip_id, destId, null)))

  const onSelectStop = useCallback((id: UUID) => {
    setHighlighted(id)
    document.getElementById(`stop-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  const days = useMemo(() => data?.itinerary?.days ?? [], [data])

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!data) return <Loading />
  const { itinerary, destinations } = data

  const generateControls = isOrganizer && (
    <div className="flex items-center gap-2">
      <Select value={solver} onChange={(e) => setSolver(e.target.value as SolverKind)} className="h-8 w-auto text-sm" aria-label="Scheduling method">
        <option value="cpsat">{SOLVER_LABEL.cpsat}</option>
        <option value="greedy">{SOLVER_LABEL.greedy}</option>
      </Select>
      <Button size="sm" onClick={() => generate.run()} loading={generate.pending}>
        {itinerary ? '↻ Regenerate' : 'Generate'}
      </Button>
    </div>
  )

  if (!itinerary) {
    return (
      <div>
        <PageHeader title="Itinerary" actions={generateControls} />
        <ErrorBox error={generate.error} />
        <Card>
          <EmptyState icon="🗺️" title="No itinerary yet">
            {isOrganizer
              ? 'When the group has voted, generate a schedule. Zoba fits the top-ranked places into each day around opening hours and travel time.'
              : "The organizer hasn't generated the itinerary yet. Check back once everyone has voted."}
          </EmptyState>
        </Card>
      </div>
    )
  }

  const visibleDays = days.filter((d) => day === null || d.day_index === day)
  const lockedCount = days.flatMap((d) => d.stops).filter((s) => s.locked).length

  return (
    <div className="space-y-4">
      <PageHeader
        title="Itinerary"
        subtitle={
          <>
            Generated {new Date(itinerary.generated_at).toLocaleString()} · {SOLVER_LABEL[itinerary.solver]}
            {lockedCount > 0 && ` · ${lockedCount} locked`}
          </>
        }
        actions={generateControls}
      />
      <ErrorBox error={generate.error ?? unlock.error} />

      {itinerary.conflicts.length > 0 && (
        <Notice tone="warn">
          <div className="mb-1 font-semibold">Heads up</div>
          <ul className="list-disc space-y-0.5 pl-5">
            {itinerary.conflicts.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Notice>
      )}

      {/* Day selector */}
      <div className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <DayChip active={day === null} onClick={() => setDay(null)} label="All days" />
        {days.map((d) => (
          <DayChip
            key={d.day_index}
            active={day === d.day_index}
            onClick={() => setDay(d.day_index)}
            color={dayColor(d.day_index)}
            label={`Day ${d.day_index + 1} · ${formatDate(d.date, { weekday: 'short', month: 'short', day: 'numeric' })}`}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="h-72 lg:sticky lg:top-20 lg:h-[calc(100vh-7rem)]">
          <TripMap
            days={days}
            destinations={destinations}
            homeBase={trip.home_base}
            selectedDay={day}
            highlighted={highlighted}
            onSelectStop={onSelectStop}
          />
        </div>

        <div className="space-y-4">
          {visibleDays.map((d) => (
            <Card key={d.day_index}>
              <div className="flex items-center gap-2 border-b border-stone-100 px-4 py-3">
                <span className="size-3 rounded-full" style={{ backgroundColor: dayColor(d.day_index) }} />
                <h3 className="font-semibold">Day {d.day_index + 1}</h3>
                <span className="text-sm text-stone-500">{formatDate(d.date, { weekday: 'long', month: 'long', day: 'numeric' })}</span>
              </div>
              {d.stops.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-stone-500">Free day — nothing fit, or everything's been scheduled.</p>
              ) : (
                <ol className="px-4 py-2">
                  <li className="py-1 text-xs text-stone-400">🏨 Start at {trip.home_base.label}</li>
                  {d.stops.map((s, i) => (
                    <StopItem
                      key={s.destination_id}
                      stop={s}
                      index={i}
                      d={destinations.get(s.destination_id)!}
                      color={dayColor(d.day_index)}
                      highlighted={highlighted === s.destination_id}
                      onHover={() => setHighlighted(s.destination_id)}
                      onLock={() => setLockTarget(s)}
                      onUnlock={() => unlock.run(s.destination_id)}
                      onEditDuration={() => setDurationTarget(s)}
                    />
                  ))}
                </ol>
              )}
            </Card>
          ))}

          <Card>
            <CardHeader title="Everyone's top pick" />
            <ul className="divide-y divide-stone-100">
              {itinerary.top_picks.map((tp) => {
                const dest = tp.destination_id ? destinations.get(tp.destination_id) : null
                return (
                  <li key={tp.user_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <Avatar name={memberName(tp.user_id)} size="sm" />
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{memberName(tp.user_id)}</span> — {dest?.name ?? 'no input'}
                    </span>
                    {tp.included ? <Badge tone="success">Included</Badge> : <Badge tone="warn">{tp.reason ?? 'Not included'}</Badge>}
                  </li>
                )
              })}
            </ul>
          </Card>

          {itinerary.unscheduled.length > 0 && (
            <Card>
              <CardHeader title="Not in the plan" subtitle="Highly ranked places that were left out, and why." />
              <ul className="divide-y divide-stone-100">
                {itinerary.unscheduled.map((u) => {
                  const dest = destinations.get(u.destination_id)
                  return (
                    <li key={u.destination_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                      <span className="text-stone-700">
                        {dest && CATEGORY_META[dest.category].emoji} {dest?.name}
                      </span>
                      <span className="text-xs text-stone-500">{u.reason}</span>
                    </li>
                  )
                })}
              </ul>
            </Card>
          )}
        </div>
      </div>

      <LockModal
        stop={lockTarget}
        dest={lockTarget ? destinations.get(lockTarget.destination_id) : undefined}
        dayCount={days.length}
        dates={days.map((d) => d.date)}
        onClose={() => setLockTarget(null)}
        onSave={async (dayIndex, time) => {
          if (!lockTarget) return
          const date = days[dayIndex].date
          setItinerary(await api.setStopLock(trip.trip_id, lockTarget.destination_id, { day_index: dayIndex, start_ts: `${date}T${time}:00` }))
          setLockTarget(null)
        }}
      />
      <DurationModal
        dest={durationTarget ? destinations.get(durationTarget.destination_id) : undefined}
        onClose={() => setDurationTarget(null)}
        onSave={async (minutes) => {
          if (!durationTarget) return
          const updated = await api.correctDuration(trip.trip_id, durationTarget.destination_id, minutes)
          setData({ ...data, destinations: new Map(destinations).set(updated.destination_id, updated) })
          setDurationTarget(null)
        }}
      />
    </div>
  )
}

function DayChip({ active, onClick, label, color }: { active: boolean; onClick: () => void; label: string; color?: string }) {
  return (
    <button
      onClick={onClick}
      className={cx(
        'flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm whitespace-nowrap',
        active ? 'border-stone-900 bg-stone-900 text-white' : 'border-stone-300 bg-white text-stone-700 hover:border-stone-400',
      )}
    >
      {color && <span className="size-2 rounded-full" style={{ backgroundColor: color }} />}
      {label}
    </button>
  )
}

function StopItem({
  stop,
  index,
  d,
  color,
  highlighted,
  onHover,
  onLock,
  onUnlock,
  onEditDuration,
}: {
  stop: ItineraryStop
  index: number
  d: Destination
  color: string
  highlighted: boolean
  onHover: () => void
  onLock: () => void
  onUnlock: () => void
  onEditDuration: () => void
}) {
  const meta = CATEGORY_META[d.category]
  const mode = MODE_META[stop.travel_mode_from_prev]
  return (
    <li id={`stop-${stop.destination_id}`} onMouseEnter={onHover}>
      <div className="flex items-center gap-2 py-1.5 pl-3 text-xs text-stone-400">
        <span className="h-4 border-l-2 border-dotted border-stone-300" />
        {mode.emoji} {stop.travel_min_from_prev} min {mode.label.toLowerCase()}
      </div>
      <div className={cx('flex gap-3 rounded-lg p-2 transition-colors', highlighted && 'bg-stone-50 ring-1 ring-stone-200')}>
        <div className="flex flex-col items-center">
          <span className="flex size-7 items-center justify-center rounded-full text-xs font-bold text-white" style={{ backgroundColor: color }}>
            {index + 1}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-sm font-semibold text-stone-900 tabular-nums">
              {timeOf(stop.start_ts)} – {timeOf(stop.end_ts)}
            </span>
            {stop.locked && <Badge tone="brand">🔒 Locked</Badge>}
            {d.requires_booking && <Badge tone="info">Book ahead</Badge>}
            {(d.hours_status === 'missing' || d.hours_status === 'unparseable') && <Badge tone="warn">Hours unknown</Badge>}
          </div>
          <div className="mt-0.5 font-medium text-stone-900">
            {meta.emoji} {d.name}
          </div>
          <div className="text-xs text-stone-500">
            {meta.label} · {hoursSummary(d)}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {stop.locked ? (
              <Button variant="ghost" size="sm" onClick={onUnlock}>
                Unlock
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={onLock}>
                🔒 Lock
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onEditDuration}>
              ⏱ {formatDuration(d.est_duration_min)}
            </Button>
            {d.website && (
              <a href={d.website} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center rounded-lg px-3 text-sm font-medium text-brand-700 hover:bg-brand-50">
                Website ↗
              </a>
            )}
          </div>
        </div>
      </div>
    </li>
  )
}

function LockModal({
  stop,
  dest,
  dayCount,
  dates,
  onClose,
  onSave,
}: {
  stop: ItineraryStop | null
  dest: Destination | undefined
  dayCount: number
  dates: string[]
  onClose: () => void
  onSave: (dayIndex: number, time: string) => Promise<void>
}) {
  const [dayIndex, setDayIndex] = useState(0)
  const [time, setTime] = useState('10:00')
  const [lastStop, setLastStop] = useState<ItineraryStop | null>(null)
  if (stop !== lastStop) {
    setLastStop(stop)
    if (stop) {
      setDayIndex(stop.day_index)
      setTime(stop.start_ts.slice(11, 16))
    }
  }
  const save = useAction(onSave)
  return (
    <Modal open={!!stop} onClose={onClose} title={`Lock ${dest?.name ?? ''}`}>
      <p className="mb-4 text-sm text-stone-600">
        Pin this stop to a day and time. The rest of the itinerary is rebuilt around it. If it can't fit, you'll see a conflict.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Day">
          <Select value={dayIndex} onChange={(e) => setDayIndex(Number(e.target.value))}>
            {Array.from({ length: dayCount }, (_, i) => (
              <option key={i} value={i}>
                Day {i + 1} · {formatDate(dates[i])}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Start time">
          <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
      </div>
      <div className="mt-4">
        <ErrorBox error={save.error} />
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => save.run(dayIndex, time)} loading={save.pending}>
          Lock & rebuild
        </Button>
      </div>
    </Modal>
  )
}

function DurationModal({ dest, onClose, onSave }: { dest: Destination | undefined; onClose: () => void; onSave: (minutes: number) => Promise<void> }) {
  const [minutes, setMinutes] = useState(60)
  const [lastDest, setLastDest] = useState<Destination | undefined>()
  if (dest !== lastDest) {
    setLastDest(dest)
    if (dest) setMinutes(dest.est_duration_min)
  }
  const save = useAction(onSave)
  return (
    <Modal open={!!dest} onClose={onClose} title="How long does this take?">
      <p className="mb-4 text-sm text-stone-600">
        We estimated <strong>{dest && formatDuration(dest.est_duration_min)}</strong> at {dest?.name}. If you know better, tell us — your correction
        improves future estimates. Regenerate the itinerary to apply it.
      </p>
      <Field label="Minutes">
        <Input type="number" min={5} max={600} step={5} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
      </Field>
      <div className="mt-4">
        <ErrorBox error={save.error} />
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => save.run(minutes)} loading={save.pending}>
          Save correction
        </Button>
      </div>
    </Modal>
  )
}
