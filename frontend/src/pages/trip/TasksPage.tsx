// F15: itinerary-generated booking tasks + custom tasks.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import type { Task } from '../../api'
import { Badge, Button, Card, EmptyState, ErrorBox, Input, Loading, PageHeader } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { formatDate } from '../../lib/format'

const today = () => new Date().toISOString().slice(0, 10)

export default function TasksPage() {
  const { trip } = useTrip()
  const { data, error, reload, setData } = useAsync(() => api.listTasks(trip.trip_id), [trip.trip_id])
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')

  const add = useAction(async (e: FormEvent) => {
    e.preventDefault()
    const t = await api.addTask(trip.trip_id, title, due || null)
    setData([...(data ?? []), t])
    setTitle('')
    setDue('')
  })
  const toggle = useAction(async (t: Task) => {
    const updated = await api.setTaskStatus(trip.trip_id, t.task_id, t.status === 'open' ? 'done' : 'open')
    setData((data ?? []).map((x) => (x.task_id === t.task_id ? updated : x)))
  })
  const remove = useAction(async (t: Task) => {
    await api.deleteTask(trip.trip_id, t.task_id)
    setData((data ?? []).filter((x) => x.task_id !== t.task_id))
  })

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return <Loading />
  const open = data.filter((t) => t.status === 'open')
  const done = data.filter((t) => t.status === 'done')

  return (
    <div className="space-y-4">
      <PageHeader title="Tasks" subtitle="Booking reminders are created automatically from the itinerary for places that need tickets in advance." />
      <ErrorBox error={add.error ?? toggle.error ?? remove.error} />

      <Card className="p-4">
        <form onSubmit={add.run} className="flex flex-col gap-2 sm:flex-row">
          <Input placeholder="Add a task, e.g. Buy Ventra passes" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Task title" />
          <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="sm:w-44" aria-label="Due date" />
          <Button type="submit" loading={add.pending} disabled={!title.trim()}>
            Add
          </Button>
        </form>
      </Card>

      <Card>
        {open.length === 0 ? (
          <EmptyState icon="✅" title="Nothing to do">
            {data.length ? 'All tasks are done.' : 'Generate an itinerary to get booking reminders, or add your own above.'}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-stone-100">
            {open.map((t) => (
              <TaskRow key={t.task_id} t={t} onToggle={() => toggle.run(t)} onDelete={() => remove.run(t)} />
            ))}
          </ul>
        )}
      </Card>

      {done.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-stone-600">Completed ({done.length})</summary>
          <Card className="mt-2">
            <ul className="divide-y divide-stone-100">
              {done.map((t) => (
                <TaskRow key={t.task_id} t={t} onToggle={() => toggle.run(t)} onDelete={() => remove.run(t)} />
              ))}
            </ul>
          </Card>
        </details>
      )}
    </div>
  )
}

function TaskRow({ t, onToggle, onDelete }: { t: Task; onToggle: () => void; onDelete: () => void }) {
  const overdue = t.status === 'open' && t.due_date !== null && t.due_date < today()
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <input type="checkbox" checked={t.status === 'done'} onChange={onToggle} className="mt-1 size-4 accent-brand-600" aria-label={`Mark "${t.title}" done`} />
      <div className="min-w-0 flex-1">
        <div className={cx('text-sm font-medium', t.status === 'done' ? 'text-stone-400 line-through' : 'text-stone-900')}>{t.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          {t.due_date && <span className={cx(overdue ? 'font-semibold text-red-600' : 'text-stone-500')}>{overdue ? 'Overdue · ' : 'Due '}{formatDate(t.due_date)}</span>}
          {t.auto_generated && <Badge tone="info">From itinerary</Badge>}
          {t.booking_url && (
            <a href={t.booking_url} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">
              Book on venue site ↗
            </a>
          )}
        </div>
      </div>
      <button onClick={onDelete} className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700" aria-label={`Delete "${t.title}"`}>
        ✕
      </button>
    </li>
  )
}
