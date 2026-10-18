import { Link, Outlet, useNavigate } from 'react-router-dom'
import { API_MODE } from '../api'
import { resetMockDb } from '../api/mock/db'
import { useAuth } from '../auth/AuthContext'
import { Avatar } from '../components/ui'

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-bold tracking-tight text-brand-700">
      <span className="flex size-8 items-center justify-center rounded-lg bg-brand-600 text-base text-white" aria-hidden>
        🧭
      </span>
      <span className="text-lg">Zoba</span>
    </Link>
  )
}

export function MockBanner() {
  const copy = {
    mock: 'Demo mode — data is mocked in your browser.',
    hybrid:
      'Hybrid mode — accounts, trips, members and expenses are live on the backend; voting, itinerary, tasks and packing are still demo data.',
  }[API_MODE as 'mock' | 'hybrid']
  if (!copy) return null
  return (
    <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-900">
      {copy}{' '}
      <button
        className="font-semibold underline"
        onClick={() => {
          if (confirm('Reset all demo data to the original seed?')) {
            resetMockDb()
            window.location.assign('/')
          }
        }}
      >
        Reset demo data
      </button>
    </div>
  )
}

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="flex min-h-screen flex-col">
      <MockBanner />
      <header className="sticky top-0 z-30 border-b border-stone-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Logo />
          {user && (
            <div className="flex items-center gap-3">
              <span className="hidden text-sm text-stone-600 sm:inline">{user.display_name}</span>
              <Avatar name={user.display_name} />
              <button
                className="text-sm font-medium text-stone-600 hover:text-stone-900"
                onClick={async () => {
                  await logout()
                  navigate('/login')
                }}
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
