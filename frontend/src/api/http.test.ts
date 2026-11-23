import { describe, expect, it, vi } from 'vitest'
import { realApi } from './http'
import { ApiError } from './types'

function mockFetch(status: number, body: unknown, statusText = '') {
  const res = new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, statusText })
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(res)
}

async function registerError(): Promise<ApiError> {
  try {
    await realApi.register!('lee@example.com', 'short', 'Lauren')
  } catch (e) {
    return e as ApiError
  }
  throw new Error('expected register to reject')
}

describe('http error messages', () => {
  it('turns a FastAPI 422 validation list into readable text', async () => {
    mockFetch(422, {
      detail: [
        { type: 'string_too_short', loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
      ],
    })
    const err = await registerError()
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.message).toBe('password: String should have at least 8 characters')
    expect(err.message).not.toContain('[object Object]')
  })

  it('joins several validation errors and strips the "Value error" prefix', async () => {
    mockFetch(422, {
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address' },
        { loc: ['body', 'password'], msg: 'Value error, password must be at most 72 bytes' },
      ],
    })
    const err = await registerError()
    expect(err.message).toBe('email: value is not a valid email address; password: password must be at most 72 bytes')
  })

  it('passes a plain string detail through unchanged', async () => {
    mockFetch(409, { detail: 'Email already registered' })
    const err = await registerError()
    expect(err.status).toBe(409)
    expect(err.message).toBe('Email already registered')
  })

  it('falls back to the status text for a non-JSON body', async () => {
    mockFetch(500, '<html>oops</html>', 'Internal Server Error')
    const err = await registerError()
    expect(err.message).toBe('Internal Server Error')
  })
})

describe('auth requests', () => {
  const wireSession = {
    access_token: 'tok-123',
    token_type: 'bearer',
    user: { id: 'u1', email: 'lee@example.com', name: 'Lauren', created_at: '2026-01-01T00:00:00Z' },
  }

  it('register posts name/email/password, stores the token, and maps the user', async () => {
    const fetchSpy = mockFetch(201, wireSession)
    const user = await realApi.register!('lee@example.com', 'longenough', 'Lauren')

    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/auth/register')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ email: 'lee@example.com', name: 'Lauren', password: 'longenough' })
    expect(user).toEqual({ user_id: 'u1', email: 'lee@example.com', display_name: 'Lauren' })
    expect(sessionStorage.getItem('zoba_token')).toBe('tok-123')
  })

  it('login posts to /auth/login without a name', async () => {
    const fetchSpy = mockFetch(200, wireSession)
    await realApi.login!('lee@example.com', 'longenough')

    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/auth/login')
    expect(JSON.parse(init?.body as string)).toEqual({ email: 'lee@example.com', password: 'longenough' })
  })

  it('sends the stored token as a bearer header', async () => {
    sessionStorage.setItem('zoba_token', 'tok-abc')
    const fetchSpy = mockFetch(200, wireSession.user)
    await realApi.currentUser!()

    const init = fetchSpy.mock.calls[0][1]
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer tok-abc')
  })

  it('currentUser returns null without a token and on 401', async () => {
    const fetchSpy = mockFetch(401, { detail: 'Not authenticated' })
    expect(await realApi.currentUser!()).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()

    sessionStorage.setItem('zoba_token', 'expired')
    expect(await realApi.currentUser!()).toBeNull()
  })

  it('logout clears the token', async () => {
    sessionStorage.setItem('zoba_token', 'tok')
    await realApi.logout!()
    expect(sessionStorage.getItem('zoba_token')).toBeNull()
  })
})
