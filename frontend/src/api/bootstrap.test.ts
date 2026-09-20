import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { ApiClientError } from './client'
import { exchangeBootstrapToken } from './bootstrap'

const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
})
afterAll(() => server.close())

describe('exchangeBootstrapToken', () => {
  it.each([200, 401])('shares one exchange and cleanup between callers for status %s', async (status) => {
    let exchanges = 0
    server.use(
      http.post('http://localhost:3000/api/auth/exchange', ({ request }) => {
        exchanges += 1
        expect(request.credentials).toBe('same-origin')
        expect(request.headers.get('X-PI-Bootstrap-Token')).toBe('secret')
        const envelope = status === 200
          ? { data: { authenticated: true }, error: null }
          : { data: null, error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } }
        return HttpResponse.json(envelope, { status })
      }),
    )
    const localStorageSpy = vi.spyOn(Storage.prototype, 'getItem')
    const sessionStorageSpy = vi.spyOn(Storage.prototype, 'setItem')
    window.history.replaceState(
      { preserved: true },
      '',
      '/scheduler?view=week&bootstrap=secret&room=101#selection',
    )
    const replaceState = vi.spyOn(window.history, 'replaceState')

    const first = exchangeBootstrapToken()
    const second = exchangeBootstrapToken()
    expect(first).toBe(second)
    const results = await Promise.allSettled([first, second])

    expect(exchanges).toBe(1)
    expect(results.map((result) => result.status)).toEqual(
      status === 200 ? ['fulfilled', 'fulfilled'] : ['rejected', 'rejected'],
    )
    if (status === 401) {
      expect((results[0] as PromiseRejectedResult).reason).toBeInstanceOf(ApiClientError)
      expect((results[0] as PromiseRejectedResult).reason).toBe(
        (results[1] as PromiseRejectedResult).reason,
      )
    }
    await expect(exchangeBootstrapToken()).resolves.toBeUndefined()
    expect(replaceState).toHaveBeenCalledOnce()
    expect(window.location.pathname).toBe('/scheduler')
    expect(window.location.search).toBe('?view=week&room=101')
    expect(window.location.hash).toBe('#selection')
    expect(window.history.state).toEqual({ preserved: true })
    expect(localStorageSpy).not.toHaveBeenCalled()
    expect(sessionStorageSpy).not.toHaveBeenCalled()
  })

  it('does nothing when the initial URL has no bootstrap token', async () => {
    const replaceState = vi.spyOn(window.history, 'replaceState')
    window.history.pushState(null, '', '/scheduler?view=week#selection')

    await exchangeBootstrapToken()

    expect(replaceState).not.toHaveBeenCalled()
  })
})
