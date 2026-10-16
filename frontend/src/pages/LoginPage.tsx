import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { USING_MOCK } from '../api'
import { useAuth } from '../auth/AuthContext'
import { Button, ErrorBox, Field, Input } from '../components/ui'
import AuthLayout from '../layouts/AuthLayout'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (user) return <Navigate to={from} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setPending(true)
    setError(null)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout title="Welcome back" subtitle="Log in to plan trips with your group.">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={error} />
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" className="w-full" loading={pending}>
          Log in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-stone-600">
        New to Zoba?{' '}
        <Link to="/register" state={{ from }} className="font-medium text-brand-700 hover:underline">
          Create an account
        </Link>
      </p>
      {USING_MOCK && (
        <div className="mt-6 rounded-lg bg-stone-100 p-3 text-xs text-stone-600">
          <div className="mb-1 font-semibold text-stone-700">Demo accounts (password: zoba)</div>
          <div className="flex flex-wrap gap-2">
            {[
              ['demo@zoba.app', 'Organizer'],
              ['maya@zoba.app', 'Member'],
            ].map(([e, role]) => (
              <button
                key={e}
                type="button"
                className="rounded-md bg-white px-2 py-1 font-medium text-stone-700 ring-1 ring-stone-200 hover:ring-brand-400"
                onClick={() => {
                  setEmail(e)
                  setPassword('zoba')
                }}
              >
                {e} <span className="text-stone-400">· {role}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </AuthLayout>
  )
}
