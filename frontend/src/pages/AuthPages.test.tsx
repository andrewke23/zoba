import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/types'
import type { User } from '../api/types'
import LoginPage from './LoginPage'
import RegisterPage from './RegisterPage'

const auth = {
  user: null as User | null,
  loading: false,
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}

vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))

beforeEach(() => {
  auth.user = null
  auth.login = vi.fn().mockResolvedValue(undefined)
  auth.register = vi.fn().mockResolvedValue(undefined)
})

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>Home page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

// Field wraps each input in a <label>, but the hint text is inside it too, so
// match on the label's start.
const nameInput = () => screen.getByLabelText(/^Your name/)
const emailInput = () => screen.getByLabelText(/^Email/)
const passwordInput = () => screen.getByLabelText(/^Password/)

describe('RegisterPage', () => {
  it('renders the signup form', () => {
    renderAt('/register')
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    expect(nameInput()).toBeRequired()
    expect(emailInput()).toHaveAttribute('type', 'email')
    expect(passwordInput()).toHaveAttribute('type', 'password')
  })

  it('requires an 8-character password, matching the backend', () => {
    renderAt('/register')
    expect(passwordInput()).toHaveAttribute('minLength', '8')
    expect(screen.getByText('At least 8 characters.')).toBeInTheDocument()
  })

  it('submits the form and navigates home on success', async () => {
    const user = userEvent.setup()
    renderAt('/register')
    await user.type(nameInput(), 'Lauren')
    await user.type(emailInput(), 'lee@example.com')
    await user.type(passwordInput(), 'longenough')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(auth.register).toHaveBeenCalledWith('lee@example.com', 'longenough', 'Lauren')
    expect(await screen.findByText('Home page')).toBeInTheDocument()
  })

  it('shows the server error message, not [object Object]', async () => {
    auth.register.mockRejectedValue(new ApiError(422, 'password: String should have at least 8 characters'))
    const user = userEvent.setup()
    renderAt('/register')
    await user.type(nameInput(), 'Lauren')
    await user.type(emailInput(), 'lee@example.com')
    await user.type(passwordInput(), 'longenough')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('password: String should have at least 8 characters')
    expect(alert).not.toHaveTextContent('[object Object]')
    expect(screen.queryByText('Home page')).not.toBeInTheDocument()
  })

  it('redirects away when already signed in', () => {
    auth.user = { user_id: 'u1', email: 'lee@example.com', display_name: 'Lauren' }
    renderAt('/register')
    expect(screen.getByText('Home page')).toBeInTheDocument()
  })

  it('links to the login page', async () => {
    const user = userEvent.setup()
    renderAt('/register')
    await user.click(screen.getByRole('link', { name: 'Log in' }))
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  })
})

describe('LoginPage', () => {
  it('logs in and navigates home', async () => {
    const user = userEvent.setup()
    renderAt('/login')
    await user.type(emailInput(), 'lee@example.com')
    await user.type(passwordInput(), 'longenough')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(auth.login).toHaveBeenCalledWith('lee@example.com', 'longenough')
    expect(await screen.findByText('Home page')).toBeInTheDocument()
  })

  it('shows an error for bad credentials and stays on the page', async () => {
    auth.login.mockRejectedValue(new ApiError(401, 'Invalid email or password'))
    const user = userEvent.setup()
    renderAt('/login')
    await user.type(emailInput(), 'lee@example.com')
    await user.type(passwordInput(), 'wrongpass')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  })

  it('links to the signup page', async () => {
    const user = userEvent.setup()
    renderAt('/login')
    await user.click(screen.getByRole('link', { name: 'Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
  })
})
