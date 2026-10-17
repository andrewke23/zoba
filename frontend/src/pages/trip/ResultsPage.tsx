// F06 (fairness-aware group ranking), F08 (vetoes), F08a (raw counts beside weighted scores).
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { Destination, RankingRow } from '../../api'
import { Avatar, Badge, Button, Card, CardHeader, ErrorBox, Loading, PageHeader } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { CATEGORY_META, pct } from '../../lib/format'

export default function ResultsPage() {
  const { trip, isOrganizer, memberName } = useTrip()
  const state = useAsync(async () => {
    const [results, destinations] = await Promise.all([api.getGroupResults(trip.trip_id), api.listDestinations(trip.trip_id)])
    return { results, destinations: new Map(destinations.map((d) => [d.destination_id, d])) }
  }, [trip.trip_id])

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!state.data) return <Loading />
  const { results, destinations } = state.data
  const ranked = results.rows.filter((r) => r.vetoed_by.length === 0)
  const vetoed = results.rows.filter((r) => r.vetoed_by.length > 0)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Group results"
        subtitle="Ranked by a fairness-aware score that balances the group's average enthusiasm with the least-happy member, so nobody gets steamrolled."
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={state.reload} loading={state.loading}>
              Refresh
            </Button>
            {isOrganizer && (
              <Link to="../itinerary">
                <Button size="sm">Build itinerary →</Button>
              </Link>
            )}
          </>
        }
      />

      <Card>
        <CardHeader title="Everyone's top pick" subtitle="Each member's highest-ranked eligible place is prioritized in the itinerary." />
        <ul className="grid gap-px bg-stone-100 sm:grid-cols-2">
          {results.top_picks.map((tp) => {
            const d = tp.destination_id ? destinations.get(tp.destination_id) : null
            return (
              <li key={tp.user_id} className="flex items-center gap-3 bg-white px-4 py-3">
                <Avatar name={memberName(tp.user_id)} />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-stone-900">{memberName(tp.user_id)}</div>
                  <div className="truncate text-sm text-stone-600">{d ? `${CATEGORY_META[d.category].emoji} ${d.name}` : 'No input yet'}</div>
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      <Card>
        <CardHeader title="Ranking" subtitle="Weighted results are shown beside the raw vote counts." />
        {/* Desktop table */}
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-sm">
            <thead className="border-b border-stone-100 text-left text-xs tracking-wide text-stone-500 uppercase">
              <tr>
                <th className="px-4 py-2 font-medium">#</th>
                <th className="px-4 py-2 font-medium">Place</th>
                <th className="px-4 py-2 font-medium">Group score</th>
                <th className="px-4 py-2 text-right font-medium" title="Least-happy member's normalized preference">Worst-off</th>
                <th className="px-4 py-2 text-right font-medium" title="Share of capped points">Weighted pts</th>
                <th className="px-4 py-2 text-right font-medium">Raw pts</th>
                <th className="px-4 py-2 text-right font-medium">Votes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {ranked.map((r) => (
                <Row key={r.destination_id} r={r} d={destinations.get(r.destination_id)!} />
              ))}
            </tbody>
          </table>
        </div>
        {/* Mobile list */}
        <ul className="divide-y divide-stone-100 md:hidden">
          {ranked.map((r) => {
            const d = destinations.get(r.destination_id)!
            return (
              <li key={r.destination_id} className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <span className="w-6 text-sm font-semibold text-stone-400">{r.rank}</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-stone-900">
                    {CATEGORY_META[d.category].emoji} {d.name}
                  </span>
                  <span className="text-sm font-semibold text-brand-700">{pct(r.group_score)}</span>
                </div>
                <div className="mt-1.5 ml-9">
                  <ScoreBar value={r.group_score} />
                  <div className="mt-1 flex gap-3 text-xs text-stone-500">
                    <span>Weighted {pct(r.weighted_points)}</span>
                    <span>Raw {r.raw_points} pts</span>
                    <span>
                      {r.raw_votes} vote{r.raw_votes === 1 ? '' : 's'}
                    </span>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      {vetoed.length > 0 && (
        <Card>
          <CardHeader title="Excluded — hard no" subtitle="These won't be scheduled, no matter how many points they got." />
          <ul className="divide-y divide-stone-100">
            {vetoed.map((r) => {
              const d = destinations.get(r.destination_id)!
              return (
                <li key={r.destination_id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
                  <span className="flex-1 text-stone-500 line-through">
                    {CATEGORY_META[d.category].emoji} {d.name}
                  </span>
                  <span className="text-xs text-stone-500">
                    {r.raw_points} raw pts · vetoed by {r.vetoed_by.map(memberName).join(', ')}
                  </span>
                  <Badge tone="danger">Hard no</Badge>
                </li>
              )
            })}
          </ul>
        </Card>
      )}

      <p className="text-xs text-stone-500">
        Point weights are capped at {results.config.point_cap} per place. Each member's scores are normalized before combining, so doing more
        comparisons doesn't give anyone extra say.
      </p>
    </div>
  )
}

function ScoreBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-stone-100">
      <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(2, value * 100)}%` }} />
    </div>
  )
}

function Row({ r, d }: { r: RankingRow; d: Destination }) {
  return (
    <tr className="hover:bg-stone-50">
      <td className="px-4 py-2.5 font-semibold text-stone-400">{r.rank}</td>
      <td className="px-4 py-2.5">
        <span className="font-medium text-stone-900">
          {CATEGORY_META[d.category].emoji} {d.name}
        </span>
      </td>
      <td className="w-48 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ScoreBar value={r.group_score} />
          <span className="w-9 text-right font-semibold text-brand-700 tabular-nums">{pct(r.group_score)}</span>
        </div>
      </td>
      <td className="px-4 py-2.5 text-right text-stone-600 tabular-nums">{pct(r.min_member_utility)}</td>
      <td className="px-4 py-2.5 text-right text-stone-600 tabular-nums">{pct(r.weighted_points)}</td>
      <td className="px-4 py-2.5 text-right text-stone-600 tabular-nums">{r.raw_points}</td>
      <td className="px-4 py-2.5 text-right text-stone-600 tabular-nums">{r.raw_votes}</td>
    </tr>
  )
}
