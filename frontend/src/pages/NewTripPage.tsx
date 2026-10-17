import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import TripForm from '../components/TripForm'
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

export default function NewTripPage() {
  const navigate = useNavigate()
  const cities = useAsync(() => api.listCities(), [])

  return (
    <div className="mx-auto max-w-2xl px-4 py-6">
      <PageHeader title="Create a trip" subtitle="You'll be the organizer. You can change these settings later." />
      <ErrorBox error={cities.error} onRetry={cities.reload} />
      {cities.data ? (
        <Card className="p-5">
          <TripForm
            cities={cities.data}
            submitLabel="Create trip"
            onSubmit={async (input) => {
              const trip = await api.createTrip(input)
              navigate(`/trips/${trip.trip_id}/settings`, { state: { justCreated: true } })
            }}
          />
        </Card>
      ) : (
        !cities.error && <Loading />
      )}
    </div>
  )
}
