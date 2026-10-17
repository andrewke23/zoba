// Packing list — in the SRS UI section but without a requirement ID yet (SRS §8).
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import type { PackingItem, UUID } from '../../api'
import { Avatar, Button, Card, CardHeader, EmptyState, ErrorBox, Input, Loading, PageHeader, Select } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'

export default function PackingPage() {
  const { trip, members, memberName } = useTrip()
  const { data, error, reload, setData } = useAsync(() => api.listPacking(trip.trip_id), [trip.trip_id])
  const [label, setLabel] = useState('')
  const [assignee, setAssignee] = useState<UUID | ''>('')

  const add = useAction(async (e: FormEvent) => {
    e.preventDefault()
    const item = await api.addPacking(trip.trip_id, label, assignee || null)
    setData([...(data ?? []), item])
    setLabel('')
  })
  const update = useAction(async (item: PackingItem) => {
    setData((data ?? []).map((x) => (x.item_id === item.item_id ? item : x)))
    await api.updatePacking(trip.trip_id, item)
  })
  const remove = useAction(async (id: UUID) => {
    await api.deletePacking(trip.trip_id, id)
    setData((data ?? []).filter((x) => x.item_id !== id))
  })

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return <Loading />
  const everyone = data.filter((i) => i.assignee_id === null)
  const assigned = data.filter((i) => i.assignee_id !== null)

  const list = (items: PackingItem[]) => (
    <ul className="divide-y divide-stone-100">
      {items.map((i) => (
        <li key={i.item_id} className="flex items-center gap-3 px-4 py-2.5">
          <input type="checkbox" className="size-4 accent-brand-600" checked={i.packed} onChange={() => update.run({ ...i, packed: !i.packed })} aria-label={`Packed ${i.label}`} />
          <span className={cx('flex-1 text-sm', i.packed && 'text-stone-400 line-through')}>{i.label}</span>
          {i.assignee_id && (
            <span className="flex items-center gap-1.5 text-xs text-stone-500">
              <Avatar name={memberName(i.assignee_id)} size="sm" />
              <span className="hidden sm:inline">{memberName(i.assignee_id)}</span>
            </span>
          )}
          <button onClick={() => remove.run(i.item_id)} className="rounded p-1 text-stone-400 hover:bg-stone-100" aria-label={`Remove ${i.label}`}>
            ✕
          </button>
        </li>
      ))}
    </ul>
  )

  return (
    <div className="space-y-4">
      <PageHeader title="Packing list" subtitle="Things everyone should bring, plus shared items one person is covering." />
      <ErrorBox error={add.error ?? update.error ?? remove.error} />
      <Card className="p-4">
        <form onSubmit={add.run} className="flex flex-col gap-2 sm:flex-row">
          <Input placeholder="Add an item…" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Item" />
          <Select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="sm:w-48" aria-label="Who brings it">
            <option value="">Everyone brings own</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name} brings for group
              </option>
            ))}
          </Select>
          <Button type="submit" loading={add.pending} disabled={!label.trim()}>
            Add
          </Button>
        </form>
      </Card>
      {data.length === 0 ? (
        <Card>
          <EmptyState icon="🎒" title="Nothing on the list yet" />
        </Card>
      ) : (
        <>
          {everyone.length > 0 && (
            <Card>
              <CardHeader title="Everyone brings" />
              {list(everyone)}
            </Card>
          )}
          {assigned.length > 0 && (
            <Card>
              <CardHeader title="Shared — one person covers it" />
              {list(assigned)}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
