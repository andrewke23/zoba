// Simulates the frontend adapter's exact wire calls through the Vite dev proxy
// (http://localhost:5173/api/v1/...) to verify end-to-end integration.
const BASE = 'http://localhost:5173/api/v1'
let failures = 0

const check = (label, ok, detail = '') => {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${ok || !detail ? '' : ` -- ${detail}`}`)
  if (!ok) failures++
}

const call = async (method, path, { token, body, raw = false } = {}) => {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  if (raw) return { status: res.status, text }
  return { status: res.status, data: text ? JSON.parse(text) : null, text }
}

const run = Math.random().toString(36).slice(2, 8)
const suffix = `${run}`

// 1. register (authSession: {email, name, password})
const reg = await call('POST', '/auth/register', { body: { email: `ui-${suffix}@example.com`, name: 'UI Tester', password: 'correct horse battery staple' } })
check('register through proxy -> 201 + token', reg.status === 201 && !!reg.data.access_token, reg.text)
const token = reg.data.access_token
const userId = reg.data.user.id
check('register maps name -> display_name contract', reg.data.user.name === 'UI Tester')

// 2. cities
const cities = await call('GET', '/cities', { token })
const chicago = cities.data.find((c) => c.city_id === 'chicago')
check('cities -> chicago with [lng, lat] center', Array.isArray(chicago?.center) && chicago.center[0] < 0 && chicago.center[1] > 0, cities.text)

// 3. createTrip (tripBody mapping, times as HH:MM)
const tripBody = {
  organizer_id: userId,
  city_id: 'chicago',
  name: `Proxy trip ${suffix}`,
  start_date: '2026-12-04',
  end_date: '2026-12-06',
  daily_start_time: '09:00',
  daily_end_time: '21:00',
  home_base_lat: 41.8781,
  home_base_lon: -87.6298,
  home_base_label: 'Hotel — 151 E Wacker Dr',
}
const created = await call('POST', '/trips', { token, body: tripBody })
check('createTrip (HH:MM times) -> 201', created.status === 201, created.text)
const tripId = created.data.id
check('trip returns invite_token + label', !!created.data.invite_token && created.data.home_base_label === 'Hotel — 151 E Wacker Dr')

// 4. listTrips
const trips = await call('GET', '/trips', { token })
const summary = trips.data.find((t) => t.id === tripId)
check('listTrips -> summary with city_name/role/count', summary?.city_name === 'Chicago' && summary?.my_role === 'organizer' && summary?.member_count === 1, trips.text)

// 5. listMembers
const members = await call('GET', `/trips/${tripId}/members`, { token })
check('listMembers -> email/display_name present', members.data[0].email?.includes('ui-') && members.data[0].display_name === 'UI Tester', members.text)

// 6. updateTrip
const updated = await call('PUT', `/trips/${tripId}`, { token, body: { name: `Renamed ${suffix}` } })
check('updateTrip -> renamed', updated.status === 200 && updated.data.name === `Renamed ${suffix}`, updated.text)

// 7. invite preview signed out (getInvite sends no auth when logged out)
const preview = await call('GET', `/invites/${created.data.invite_token}`)
check('getInvite works with NO auth header', preview.status === 200 && preview.data.organizer_name === 'UI Tester', preview.text)

// 8. second user joins via link
const reg2 = await call('POST', '/auth/register', { body: { email: `ui2-${suffix}@example.com`, name: 'Friend', password: 'correct horse battery staple' } })
const token2 = reg2.data.access_token
const joined = await call('POST', `/invites/${created.data.invite_token}/join`, { token: token2 })
check('join via invite link -> joined', joined.status === 200 && joined.data.status === 'joined', joined.text)

// 9. addExpense exactly as http.ts maps it (payer share dropped, ISO date, Money strings)
const expenseBody = {
  payer_id: userId,
  description: 'Proxy dinner',
  amount: '30.00',
  date: new Date().toISOString(),
  splits: [{ debtor_id: reg2.data.user.id, amount_owed: '15.00' }],
}
const expense = await call('POST', `/trips/${tripId}/expenses`, { token, body: expenseBody })
check('addExpense adapter shape -> 201 with payer remainder', expense.status === 201, expense.text)
const shares = Object.fromEntries(expense.data.splits.map((s) => [s.debtor_id, s.amount_owed]))
check('payer got the unallocated remainder', shares[userId] === '15.00' && shares[reg2.data.user.id] === '15.00', JSON.stringify(shares))

// 10. settlement (adapter reads balances + transfers)
const settlement = await call('GET', `/trips/${tripId}/settlement`, { token: token2 })
check('settlement -> balances + one transfer', settlement.data.transfers.length === 1 && settlement.data.balances.length === 2 && settlement.data.transfers[0].amount === '15.00', settlement.text)

// 11. cost-estimate (adapter builds per-member table from this)
const estimate = await call('GET', `/trips/${tripId}/cost-estimate`, { token })
check('cost-estimate -> 200 with stop counts', estimate.status === 200 && typeof estimate.data.per_person_total === 'string' && estimate.data.currency === 'USD', estimate.text)

// 12. unimplemented domain gives a clean 404/405/501-style error, not a crash
const tasks = await call('GET', `/trips/${tripId}/tasks`, { token, raw: true })
check('unimplemented /tasks endpoint responds cleanly', tasks.status === 404 || tasks.status === 405, tasks.text)

console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL PROXY INTEGRATION CHECKS PASSED')
process.exit(failures ? 1 : 0)
