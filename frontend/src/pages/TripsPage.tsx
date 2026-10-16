import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, Button, Card, EmptyState, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { formatDateRange } from '../lib/format'

export default function TripsPage() {
  const { data, error, loading, reload } = useAsync(() => api.listTrips(), [])

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <PageHeader
        title="My trips"
        subtitle="Trips you organize or have joined."
        actions={
          <Link to="/trips/new">
            <Button>+ New trip</Button>
          </Link>
        }
      />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? (
        <Loading />
      ) : data && data.length === 0 ? (
        <Card>
          <EmptyState icon="🧳" title="No trips yet">
            Create a trip and share the invite link, or open an invite link a friend sent you.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {data?.map((t) => (
            <Link key={t.trip_id} to={`/trips/${t.trip_id}`} className="group">
              <Card className="h-full p-5 transition-shadow group-hover:shadow-md">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-semibold text-stone-900 group-hover:text-brand-700">{t.name}</h3>
                  <Badge tone={t.my_role === 'organizer' ? 'brand' : 'neutral'}>{t.my_role === 'organizer' ? 'Organizer' : 'Member'}</Badge>
                </div>
                <p className="mt-1 text-sm text-stone-600">
                  📍 {t.city_name} · {formatDateRange(t.start_date, t.end_date)}
                </p>
                <p className="mt-3 text-xs text-stone-500">
                  {t.member_count} traveler{t.member_count === 1 ? '' : 's'}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
