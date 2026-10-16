// UC-07 / F11: run both schedulers on identical inputs and compare quality + runtime.
import { Navigate } from 'react-router-dom'
import { USING_MOCK, api } from '../../api'
import type { SolverMetrics } from '../../api'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorBox, Notice, PageHeader } from '../../components/ui'
import { useAction } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { pct } from '../../lib/format'
import { useState } from 'react'

const LABEL = { greedy: 'Greedy heuristic', cpsat: 'OR-Tools CP-SAT' } as const

const METRICS: { key: keyof SolverMetrics; label: string; fmt: (m: SolverMetrics) => string; better: 'high' | 'low' }[] = [
  { key: 'group_score', label: 'Group score', fmt: (m) => pct(m.group_score), better: 'high' },
  { key: 'min_member_utility', label: 'Worst-off member', fmt: (m) => pct(m.min_member_utility), better: 'high' },
  { key: 'stops_scheduled', label: 'Stops scheduled', fmt: (m) => String(m.stops_scheduled), better: 'high' },
  { key: 'travel_min_total', label: 'Total travel', fmt: (m) => `${m.travel_min_total} min`, better: 'low' },
  { key: 'runtime_ms', label: 'Runtime', fmt: (m) => `${m.runtime_ms.toFixed(1)} ms`, better: 'low' },
]

export default function SolversPage() {
  const { trip, isOrganizer } = useTrip()
  const [runs, setRuns] = useState<SolverMetrics[] | null>(null)
  const compare = useAction(async () => setRuns(await api.compareSolvers(trip.trip_id)))

  if (!isOrganizer) return <Navigate to=".." replace />

  return (
    <div className="space-y-4">
      <PageHeader
        title="Compare solvers"
        subtitle="Run the fast heuristic and the constraint solver on the exact same inputs. This doesn't change the saved itinerary."
        actions={
          <Button onClick={() => compare.run()} loading={compare.pending}>
            {runs ? 'Run again' : 'Run comparison'}
          </Button>
        }
      />
      {USING_MOCK && (
        <Notice tone="warn">Demo mode: both methods are simple in-browser stand-ins. Real numbers come from the backend solver.</Notice>
      )}
      <ErrorBox error={compare.error} />
      <Card>
        <CardHeader title="Results" />
        {!runs ? (
          <EmptyState icon="🧪" title="No runs yet">
            Press <strong>Run comparison</strong> to evaluate both methods.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-stone-100 text-left text-xs tracking-wide text-stone-500 uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">Metric</th>
                  {runs.map((r) => (
                    <th key={r.solver} className="px-4 py-2 text-right font-medium">
                      {LABEL[r.solver]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {METRICS.map((m) => {
                  const vals = runs.map((r) => Number(r[m.key]))
                  const best = m.better === 'high' ? Math.max(...vals) : Math.min(...vals)
                  return (
                    <tr key={m.key}>
                      <td className="px-4 py-2.5 text-stone-700">{m.label}</td>
                      {runs.map((r) => (
                        <td key={r.solver} className="px-4 py-2.5 text-right tabular-nums">
                          <span className={Number(r[m.key]) === best && vals.some((v) => v !== best) ? 'font-semibold text-emerald-700' : ''}>{m.fmt(r)}</span>
                        </td>
                      ))}
                    </tr>
                  )
                })}
                <tr>
                  <td className="px-4 py-2.5 text-stone-700">Feasible</td>
                  {runs.map((r) => (
                    <td key={r.solver} className="px-4 py-2.5 text-right">
                      {r.feasible ? <Badge tone="success">Yes</Badge> : <Badge tone="danger">Conflicts</Badge>}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
