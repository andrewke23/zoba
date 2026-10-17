import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { Button, Card, ErrorBox, Loading } from '../components/ui'
import { useAction, useAsync } from '../hooks/useAsync'
import { formatDateRange, formatTime } from '../lib/format'

export default function JoinPage() {
  const { token = '' } = useParams()
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const invite = useAsync(() => api.getInvite(token), [token])
  const join = useAction(async () => {
    const trip = await api.joinTrip(token)
    navigate(`/trips/${trip.trip_id}/preferences`)
  })

  if (invite.loading || authLoading) return <Loading />

  return (
    <div className="mx-auto max-w-md px-4 py-10">
      {invite.error ? (
        <ErrorBox error={invite.error} />
      ) : (
        invite.data && (
          <Card className="p-6 text-center">
            <div className="mb-2 text-4xl">✈️</div>
            <p className="text-sm text-stone-500">{invite.data.organizer_name} invited you to</p>
            <h1 className="mt-1 text-2xl font-bold text-stone-900">{invite.data.trip.name}</h1>
            <p className="mt-2 text-sm text-stone-600">
              📍 {invite.data.city_name} · {formatDateRange(invite.data.trip.start_date, invite.data.trip.end_date)}
            </p>
            <p className="text-sm text-stone-600">
              Days run {formatTime(invite.data.trip.day_start)} – {formatTime(invite.data.trip.day_end)}
            </p>
            <div className="mt-6 space-y-3">
              <ErrorBox error={join.error} />
              {user ? (
                <Button className="w-full" loading={join.pending} onClick={() => join.run()}>
                  Join as {user.display_name}
                </Button>
              ) : (
                <>
                  <Link to="/register" state={{ from: `/join/${token}` }} className="block">
                    <Button className="w-full">Create an account to join</Button>
                  </Link>
                  <Link to="/login" state={{ from: `/join/${token}` }} className="block text-sm font-medium text-brand-700">
                    I already have an account
                  </Link>
                </>
              )}
            </div>
          </Card>
        )
      )}
    </div>
  )
}
