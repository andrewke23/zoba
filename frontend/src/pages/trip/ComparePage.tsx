// F03 / F04: adaptive pairwise comparisons.
import { useCallback, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { ComparisonProgress, Destination, UUID } from '../../api'
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, ProgressBar, Spinner } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { CATEGORY_META, formatDuration, usd } from '../../lib/format'

export default function ComparePage() {
  const { trip, reload: reloadTrip } = useTrip()
  const state = useAsync(async () => {
    const [destinations, progress] = await Promise.all([api.listDestinations(trip.trip_id), api.getComparisonProgress(trip.trip_id)])
    return { destinations: new Map(destinations.map((d) => [d.destination_id, d])), progress }
  }, [trip.trip_id])
  const { data, setData } = state

  const choose = useAction(async (chosen: UUID) => {
    if (!data?.progress.next) return
    const progress: ComparisonProgress = await api.submitComparison(trip.trip_id, data.progress.next, chosen)
    setData({ ...data, progress })
    if (progress.done === progress.target) void reloadTrip()
  })

  const pick = useCallback(
    (side: 'a' | 'b') => {
      const next = data?.progress.next
      if (!next || choose.pending) return
      void choose.run(side === 'a' ? next.dest_a : next.dest_b)
    },
    [data, choose],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') pick('a')
      if (e.key === 'ArrowRight') pick('b')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pick])

  const pair = useMemo(() => {
    if (!data?.progress.next) return null
    return [data.destinations.get(data.progress.next.dest_a)!, data.destinations.get(data.progress.next.dest_b)!] as const
  }, [data])

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!data) return <Loading />
  const { done, target } = data.progress
  const finished = done >= target

  return (
    <div>
      <PageHeader title="This or that?" subtitle="Tap the place you'd rather visit. Each answer helps Zoba pick the next most useful question." />

      <div className="mb-5">
        <div className="mb-1 flex justify-between text-sm">
          <span className="font-medium text-stone-800">
            {done} / {target} comparisons
          </span>
          {finished && <Badge tone="success">Minimum reached</Badge>}
        </div>
        <ProgressBar value={Math.min(done, target)} max={target} />
      </div>

      {finished && (
        <div className="mb-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          Nice — that's enough for a solid ranking. Keep going to sharpen it, or{' '}
          <Link to="../results" className="font-semibold underline">
            see the group results
          </Link>
          .
        </div>
      )}

      <ErrorBox error={choose.error} />

      {pair ? (
        <div className="relative">
          <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
            <ChoiceCard d={pair[0]} hint="←" onClick={() => pick('a')} disabled={choose.pending} />
            <ChoiceCard d={pair[1]} hint="→" onClick={() => pick('b')} disabled={choose.pending} />
          </div>
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden>
            <span className="flex size-10 items-center justify-center rounded-full bg-white text-sm font-bold text-stone-500 shadow ring-1 ring-stone-200">
              {choose.pending ? <Spinner className="size-4" /> : 'or'}
            </span>
          </div>
          <p className="mt-3 hidden text-center text-xs text-stone-400 sm:block">Tip: use ← and → keys</p>
        </div>
      ) : (
        <Card>
          <EmptyState icon="🎉" title="No more pairs to compare">
            You've compared everything worth asking about.{' '}
            <Link to="../results" className="font-medium text-brand-700">
              See group results →
            </Link>
          </EmptyState>
        </Card>
      )}
    </div>
  )
}

function ChoiceCard({ d, hint, onClick, disabled }: { d: Destination; hint: string; onClick: () => void; disabled: boolean }) {
  const meta = CATEGORY_META[d.category]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cx(
        'group flex min-h-44 flex-col rounded-2xl border-2 border-stone-200 bg-white p-5 text-left shadow-sm transition-all',
        'hover:-translate-y-0.5 hover:border-brand-400 hover:shadow-md focus-visible:border-brand-500 focus-visible:outline-none active:scale-[0.99] disabled:opacity-60',
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-3xl" aria-hidden>
          {meta.emoji}
        </span>
        <span className="hidden text-xs text-stone-300 group-hover:text-brand-500 sm:inline">{hint}</span>
      </div>
      <h3 className="mt-3 text-lg font-bold text-stone-900">{d.name}</h3>
      <p className="text-xs text-stone-500">
        {meta.label} · {d.admission_cost_usd ? usd(d.admission_cost_usd) : 'Free'} · ~{formatDuration(d.est_duration_min)}
      </p>
      {d.description && <p className="mt-2 line-clamp-3 text-sm text-stone-600">{d.description}</p>}
    </button>
  )
}
