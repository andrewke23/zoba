/* eslint-disable react-refresh/only-export-components -- test helpers, never hot-reloaded */
// Renders a page inside a router and, for trip pages, a TripContext — so page
// tests don't need the real TripLayout (which fetches the trip itself).
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { vi } from 'vitest'
import { TripContext } from '../layouts/TripContext'
import type { TripCtx } from '../layouts/TripContext'
import { city, memberName, members, trip } from './fixtures'

export function tripCtx(overrides: Partial<TripCtx> = {}): TripCtx {
  return {
    trip,
    city,
    members,
    myRole: 'organizer',
    isOrganizer: true,
    memberName,
    reload: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

/** Render `page` at `path`; any other route renders "Navigated to <path>". */
export function renderPage(page: ReactElement, { path = '/', ctx }: { path?: string; ctx?: Partial<TripCtx> | false } = {}) {
  const element = ctx === false ? page : <TripContext.Provider value={tripCtx(ctx)}>{page}</TripContext.Provider>
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path} element={element} />
        <Route path="*" element={<NavigatedTo />} />
      </Routes>
    </MemoryRouter>,
  )
}

function NavigatedTo() {
  return <div data-testid="navigated">{useLocation().pathname}</div>
}
