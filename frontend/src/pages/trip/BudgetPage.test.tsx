import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../../api'
import { estimate, expenses, ME, settlement } from '../../test/fixtures'
import { renderPage } from '../../test/render'
import BudgetPage from './BudgetPage'

vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: ME }) }))

function mockBudget(overrides: { expenses?: typeof expenses; settlement?: typeof settlement } = {}) {
  return {
    estimate: vi.spyOn(api, 'getCostEstimate').mockResolvedValue(estimate),
    expenses: vi.spyOn(api, 'listExpenses').mockResolvedValue(overrides.expenses ?? expenses),
    settlement: vi.spyOn(api, 'getSettlement').mockResolvedValue(overrides.settlement ?? settlement),
  }
}

const renderBudget = () => renderPage(<BudgetPage />, { path: '/trips/t1/budget' })


describe('BudgetPage', () => {
  it('shows the per-person cost estimate and its assumptions', async () => {
    mockBudget()
    renderBudget()
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + Ana + Ben
    expect(within(rows[1]).getAllByRole('cell').map((c) => c.textContent)).toEqual(['Ana', '$40', '$12.50', '$60', '$113'])
    expect(screen.getByText(/Transit is estimated at CTA fares\./)).toBeInTheDocument()
  })

  it('lists expenses with payer, split and total', async () => {
    mockBudget()
    renderBudget()
    expect(await screen.findByText('1 expense · $90.00 total')).toBeInTheDocument()
    expect(screen.getByText('Dinner')).toBeInTheDocument()
    expect(screen.getByText('Ana paid · split 3 ways')).toBeInTheDocument()
  })

  it('shows balances and the suggested payments', async () => {
    mockBudget()
    renderBudget()
    expect(await screen.findByText('+$60.00')).toBeInTheDocument()
    expect(screen.getAllByText('-$30.00')).toHaveLength(2)
    expect(screen.getByText('paid $90.00 · share $30.00')).toBeInTheDocument()

    const payments = screen.getByText('Suggested payments').parentElement!
    const items = within(payments).getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual(['Ben→Ana$30.00', 'Cy→Ana$30.00'])
  })

  it('shows empty states when nothing has been logged', async () => {
    mockBudget({ expenses: [], settlement: { balances: [], transfers: [] } })
    renderBudget()
    expect(await screen.findByText('No expenses yet')).toBeInTheDocument()
    expect(screen.getByText('0 expenses · $0.00 total')).toBeInTheDocument()
    expect(screen.getByText("Everyone's even. 🎉")).toBeInTheDocument()
  })

  it('deletes an expense and reloads the page data', async () => {
    const mocks = mockBudget()
    const del = vi.spyOn(api, 'deleteExpense').mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderBudget()
    await user.click(await screen.findByRole('button', { name: 'Delete expense' }))

    expect(del).toHaveBeenCalledWith('t1', 'e1')
    await vi.waitFor(() => expect(mocks.expenses).toHaveBeenCalledTimes(2))
    expect(mocks.settlement).toHaveBeenCalledTimes(2)
  })

  it('shows an error if deleting fails', async () => {
    mockBudget()
    vi.spyOn(api, 'deleteExpense').mockRejectedValue(new ApiError(403, 'Only the payer can delete this expense'))
    const user = userEvent.setup()
    renderBudget()
    await user.click(await screen.findByRole('button', { name: 'Delete expense' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only the payer can delete this expense')
  })

  it('shows the load error', async () => {
    vi.spyOn(api, 'getCostEstimate').mockRejectedValue(new ApiError(500, 'Estimate failed'))
    vi.spyOn(api, 'listExpenses').mockResolvedValue([])
    vi.spyOn(api, 'getSettlement').mockResolvedValue({ balances: [], transfers: [] })
    renderBudget()
    expect(await screen.findByRole('alert')).toHaveTextContent('Estimate failed')
  })
})

describe('Add expense dialog', () => {
  async function openDialog() {
    const user = userEvent.setup()
    renderBudget()
    await user.click(await screen.findByRole('button', { name: '+ Add' }))
    return { user, dialog: screen.getByRole('dialog', { name: 'Add an expense' }) }
  }

  it('splits evenly between everyone by default, paid by me', async () => {
    const mocks = mockBudget()
    const add = vi.spyOn(api, 'addExpense').mockResolvedValue(expenses[0])
    const { user, dialog } = await openDialog()

    expect(within(dialog).getByLabelText('Paid by')).toHaveValue('u-ana')
    await user.type(within(dialog).getByLabelText('What was it for?'), '  Pizza  ')
    await user.type(within(dialog).getByLabelText('Amount (USD)'), '10')
    expect(within(dialog).getByText('$3.33 each')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Add expense' }))

    // 1000 cents / 3: the leftover cent goes to the first person.
    expect(add).toHaveBeenCalledWith('t1', {
      payer_id: 'u-ana',
      amount_cents: 1000,
      description: 'Pizza',
      shares: [
        { user_id: 'u-ana', share_cents: 334 },
        { user_id: 'u-ben', share_cents: 333 },
        { user_id: 'u-cy', share_cents: 333 },
      ],
    })
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(mocks.expenses).toHaveBeenCalledTimes(2)
  })

  it('only splits between the people left checked, with another payer', async () => {
    mockBudget()
    const add = vi.spyOn(api, 'addExpense').mockResolvedValue(expenses[0])
    const { user, dialog } = await openDialog()

    await user.type(within(dialog).getByLabelText('Amount (USD)'), '30.50')
    await user.selectOptions(within(dialog).getByLabelText('Paid by'), 'u-ben')
    await user.click(within(dialog).getByRole('checkbox', { name: 'Cy' }))
    await user.click(within(dialog).getByRole('button', { name: 'Add expense' }))

    expect(add.mock.calls[0][1]).toEqual({
      payer_id: 'u-ben',
      amount_cents: 3050,
      description: '',
      shares: [
        { user_id: 'u-ana', share_cents: 1525 },
        { user_id: 'u-ben', share_cents: 1525 },
      ],
    })
  })

  it('cannot be submitted without an amount or without anyone to split with', async () => {
    mockBudget()
    const { user, dialog } = await openDialog()
    const submit = within(dialog).getByRole('button', { name: 'Add expense' })
    expect(submit).toBeDisabled()

    await user.type(within(dialog).getByLabelText('Amount (USD)'), '20')
    expect(submit).toBeEnabled()

    for (const name of ['Ana', 'Ben', 'Cy']) await user.click(within(dialog).getByRole('checkbox', { name }))
    expect(submit).toBeDisabled()
  })

  it('keeps the dialog open and shows the error when saving fails', async () => {
    mockBudget()
    vi.spyOn(api, 'addExpense').mockRejectedValue(new ApiError(422, 'amount: Input should be greater than 0'))
    const { user, dialog } = await openDialog()
    await user.type(within(dialog).getByLabelText('Amount (USD)'), '5')
    await user.click(within(dialog).getByRole('button', { name: 'Add expense' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('amount: Input should be greater than 0')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('closes with Cancel or Escape', async () => {
    mockBudget()
    const { user, dialog } = await openDialog()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '+ Add' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
