// F16 (cost estimate) + F17 (shared expenses and settlement).
import { useState } from 'react'
import { api } from '../../api'
import type { ExpenseInput, UUID } from '../../api'
import { useAuth } from '../../auth/AuthContext'
import { Avatar, Button, Card, CardHeader, EmptyState, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useAction, useAsync } from '../../hooks/useAsync'
import { useTrip } from '../../layouts/TripContext'
import { cents, usd } from '../../lib/format'

export default function BudgetPage() {
  const { trip, members, memberName } = useTrip()
  const state = useAsync(async () => {
    const [estimate, expenses, settlement] = await Promise.all([
      api.getCostEstimate(trip.trip_id),
      api.listExpenses(trip.trip_id),
      api.getSettlement(trip.trip_id),
    ])
    return { estimate, expenses, settlement }
  }, [trip.trip_id])
  const [adding, setAdding] = useState(false)
  const remove = useAction(async (id: UUID) => {
    await api.deleteExpense(trip.trip_id, id)
    await state.reload()
  })

  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!state.data) return <Loading />
  const { estimate, expenses, settlement } = state.data
  const total = expenses.reduce((s, e) => s + e.amount_cents, 0)

  return (
    <div className="space-y-6">
      <PageHeader title="Costs & expenses" subtitle="Estimate what the trip will cost, then log what people actually paid and settle up." />

      {/* F16 */}
      <Card>
        <CardHeader title="Estimated cost per person" subtitle="Admission + transit + meals, from the current itinerary." />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-stone-100 text-left text-xs tracking-wide text-stone-500 uppercase">
              <tr>
                <th className="px-4 py-2 font-medium">Traveler</th>
                <th className="px-4 py-2 text-right font-medium">Admission</th>
                <th className="px-4 py-2 text-right font-medium">Transit</th>
                <th className="px-4 py-2 text-right font-medium">Meals</th>
                <th className="px-4 py-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {estimate.per_member.map((l) => (
                <tr key={l.user_id}>
                  <td className="px-4 py-2.5 whitespace-nowrap">{memberName(l.user_id)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{usd(l.admission_usd)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{usd(l.transport_usd, 2)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{usd(l.meals_usd)}</td>
                  <td className="px-4 py-2.5 text-right font-semibold tabular-nums">{usd(l.total_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="space-y-0.5 border-t border-stone-100 px-4 py-3 text-xs text-stone-500">
          {estimate.assumptions.map((a) => (
            <li key={a}>• {a}</li>
          ))}
        </ul>
      </Card>

      {/* F17 */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Shared expenses"
            subtitle={`${expenses.length} expense${expenses.length === 1 ? '' : 's'} · ${cents(total)} total`}
            action={
              <Button size="sm" onClick={() => setAdding(true)}>
                + Add
              </Button>
            }
          />
          <ErrorBox error={remove.error} />
          {expenses.length === 0 ? (
            <EmptyState icon="🧾" title="No expenses yet">
              Log anything someone paid for the group.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-stone-100">
              {expenses.map((e) => (
                <li key={e.expense_id} className="flex items-start gap-3 px-4 py-3">
                  <Avatar name={memberName(e.payer_id)} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-stone-900">{e.description || 'Expense'}</div>
                    <div className="text-xs text-stone-500">
                      {memberName(e.payer_id)} paid · split {e.shares.length} way{e.shares.length === 1 ? '' : 's'}
                    </div>
                  </div>
                  <div className="text-sm font-semibold tabular-nums">{cents(e.amount_cents)}</div>
                  <button onClick={() => remove.run(e.expense_id)} className="rounded p-1 text-stone-400 hover:bg-stone-100" aria-label="Delete expense">
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Settle up" subtitle="The fewest payments that square everyone up." />
          <ul className="divide-y divide-stone-100">
            {settlement.balances.map((b) => (
              <li key={b.user_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <Avatar name={memberName(b.user_id)} size="sm" />
                <span className="flex-1">{memberName(b.user_id)}</span>
                <span className="text-xs text-stone-400">
                  paid {cents(b.paid_cents)} · share {cents(b.owed_cents)}
                </span>
                <span className={cx('w-24 text-right font-semibold tabular-nums', b.net_cents > 0 ? 'text-emerald-700' : b.net_cents < 0 ? 'text-red-600' : 'text-stone-400')}>
                  {b.net_cents > 0 ? '+' : ''}
                  {cents(b.net_cents)}
                </span>
              </li>
            ))}
          </ul>
          <div className="border-t border-stone-100 bg-stone-50 px-4 py-3">
            <div className="mb-2 text-xs font-semibold tracking-wide text-stone-500 uppercase">Suggested payments</div>
            {settlement.transfers.length === 0 ? (
              <p className="text-sm text-stone-500">Everyone's even. 🎉</p>
            ) : (
              <ul className="space-y-2">
                {settlement.transfers.map((t, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <span className="font-medium">{memberName(t.from_user_id)}</span>
                    <span className="text-stone-400">→</span>
                    <span className="font-medium">{memberName(t.to_user_id)}</span>
                    <span className="ml-auto font-semibold tabular-nums">{cents(t.amount_cents)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-stone-400">Zoba doesn't move money — settle with your usual payment app.</p>
          </div>
        </Card>
      </div>

      <AddExpenseModal
        open={adding}
        onClose={() => setAdding(false)}
        memberIds={members.map((m) => m.user_id)}
        memberName={memberName}
        onSave={async (input) => {
          await api.addExpense(trip.trip_id, input)
          setAdding(false)
          await state.reload()
        }}
      />
    </div>
  )
}

/** Split `total` cents evenly; leftover cents go to the first few people. */
function evenSplit(total: number, ids: UUID[]) {
  const base = Math.floor(total / ids.length)
  const extra = total - base * ids.length
  return ids.map((user_id, i) => ({ user_id, share_cents: base + (i < extra ? 1 : 0) }))
}

function AddExpenseModal({
  open,
  onClose,
  memberIds,
  memberName,
  onSave,
}: {
  open: boolean
  onClose: () => void
  memberIds: UUID[]
  memberName: (id: UUID) => string
  onSave: (input: ExpenseInput) => Promise<void>
}) {
  const { user } = useAuth()
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [payer, setPayer] = useState<UUID>(user?.user_id ?? memberIds[0])
  const [split, setSplit] = useState<Set<UUID>>(new Set(memberIds))
  const save = useAction(onSave)

  const amountCents = Math.round(parseFloat(amount || '0') * 100)
  const ids = memberIds.filter((id) => split.has(id))
  const valid = amountCents > 0 && ids.length > 0

  return (
    <Modal open={open} onClose={onClose} title="Add an expense">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!valid) return
          await save.run({ payer_id: payer, amount_cents: amountCents, description: description.trim(), shares: evenSplit(amountCents, ids) })
          setDescription('')
          setAmount('')
        }}
      >
        <ErrorBox error={save.error} />
        <Field label="What was it for?">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Dinner at Lou Malnati's" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (USD)">
            <Input type="number" inputMode="decimal" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Paid by">
            <Select value={payer} onChange={(e) => setPayer(e.target.value)}>
              {memberIds.map((id) => (
                <option key={id} value={id}>
                  {memberName(id)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-stone-700">Split evenly between</legend>
          <div className="flex flex-wrap gap-2">
            {memberIds.map((id) => (
              <label
                key={id}
                className={cx('flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-sm', split.has(id) ? 'border-brand-500 bg-brand-50' : 'border-stone-300')}
              >
                <input
                  type="checkbox"
                  className="accent-brand-600"
                  checked={split.has(id)}
                  onChange={() =>
                    setSplit((s) => {
                      const n = new Set(s)
                      if (n.has(id)) n.delete(id)
                      else n.add(id)
                      return n
                    })
                  }
                />
                {memberName(id)}
              </label>
            ))}
          </div>
          {valid && <p className="mt-2 text-xs text-stone-500">{cents(Math.floor(amountCents / ids.length))} each</p>}
        </fieldset>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={save.pending} disabled={!valid}>
            Add expense
          </Button>
        </div>
      </form>
    </Modal>
  )
}
