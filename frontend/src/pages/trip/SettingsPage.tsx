// Organizer-only: trip configuration (F02), invite link, membership.
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { Member } from '../../api'
import TripForm from '../../components/TripForm'
import { Avatar, Badge, Button, Card, CardHeader, ErrorBox, Input, Loading, Notice, PageHeader } from '../../components/ui'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'

export default function SettingsPage() {
  const { trip, members, isOrganizer, reload } = useTrip()
  const justCreated = !!(useLocation().state as { justCreated?: boolean } | null)?.justCreated
  const navigate = useNavigate()
  const cities = useAsync(() => api.listCities(), [])
  const [copied, setCopied] = useState(false)
  const [saved, setSaved] = useState(false)
  const remove = useAction(async (m: Member) => {
    if (!confirm(`Remove ${m.display_name} from the trip?`)) return
    await api.removeMember(trip.trip_id, m.user_id)
    await reload()
  })

  if (!isOrganizer) return <Navigate to=".." replace />

  const inviteUrl = `${window.location.origin}/join/${trip.invite_token}`
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard blocked — the input is selectable as a fallback
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Trip settings" subtitle="Only you, the organizer, can see this page." />
      {justCreated && <Notice>Trip created! Share the invite link below with your group (3–8 travelers works best).</Notice>}

      <Card>
        <CardHeader title="Invite link" subtitle="Anyone with this link can join after signing in." />
        <div className="flex flex-col gap-2 p-4 sm:flex-row">
          <Input readOnly value={inviteUrl} onFocus={(e) => e.target.select()} aria-label="Invite link" />
          <Button variant="secondary" onClick={copy}>
            {copied ? 'Copied ✓' : 'Copy link'}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader title="Members" subtitle={`${members.length} of 8`} />
        <ErrorBox error={remove.error} />
        <ul className="divide-y divide-stone-100">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center gap-3 px-4 py-3">
              <Avatar name={m.display_name} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{m.display_name}</div>
                <div className="truncate text-xs text-stone-500">{m.email}</div>
              </div>
              {m.role === 'organizer' ? (
                <Badge tone="brand">Organizer</Badge>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => remove.run(m)}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader title="Trip details" subtitle="Changing dates or times means you should regenerate the itinerary." />
        <div className="p-4">
          {saved && (
            <div className="mb-4">
              <Notice>Saved.</Notice>
            </div>
          )}
          <ErrorBox error={cities.error} />
          {cities.data ? (
            <TripForm
              cities={cities.data}
              initial={{
                name: trip.name,
                city_id: trip.city_id,
                start_date: trip.start_date,
                end_date: trip.end_date,
                day_start: trip.day_start,
                day_end: trip.day_end,
                home_base: trip.home_base,
              }}
              submitLabel="Save changes"
              onSubmit={async (input) => {
                await api.updateTrip(trip.trip_id, input)
                await reload()
                setSaved(true)
                if (justCreated) navigate('.', { replace: true, state: null })
              }}
            />
          ) : (
            <Loading />
          )}
        </div>
      </Card>
    </div>
  )
}
