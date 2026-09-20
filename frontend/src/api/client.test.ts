import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { ApiClientError, apiRequest } from './client'

const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('apiRequest', () => {
  it('returns a successful envelope with same-origin credentials and JSON headers', async () => {
    server.use(
      http.post('http://localhost:3000/api/example', async ({ request }) => {
        expect(request.credentials).toBe('same-origin')
        expect(request.headers.get('content-type')).toBe('application/json')
        expect(await request.json()).toEqual({ name: 'Ada' })
        return HttpResponse.json({
          data: { id: 1 },
          workspace_version: 'workspace-1',
          warnings: ['Using fallback data'],
          error: null,
        })
      }),
    )

    await expect(
      apiRequest<{ id: number }>('/api/example', {
        method: 'POST',
        body: JSON.stringify({ name: 'Ada' }),
      }),
    ).resolves.toEqual({
      data: { id: 1 },
      workspace_version: 'workspace-1',
      warnings: ['Using fallback data'],
      error: null,
    })
  })

  it('preserves FormData content headers', async () => {
    server.use(
      http.post('http://localhost:3000/api/upload', ({ request }) => {
        expect(request.headers.get('content-type')).toMatch(/^multipart\/form-data; boundary=/)
        return HttpResponse.json({ data: { accepted: true }, error: null })
      }),
    )
    const body = new FormData()
    body.set('file', new File(['test'], 'test.txt'))

    await expect(
      apiRequest<{ accepted: boolean }>('/api/upload', { method: 'POST', body }),
    ).resolves.toEqual({
      data: { accepted: true },
      workspace_version: null,
      warnings: [],
      error: null,
    })
  })

  it('normalizes a valid wire envelope with missing data and error fields', async () => {
    server.use(
      http.get('http://localhost:3000/api/defaults', () =>
        HttpResponse.json({ warnings: [] }),
      ),
    )

    await expect(apiRequest('/api/defaults')).resolves.toEqual({
      data: null,
      workspace_version: null,
      warnings: [],
      error: null,
    })
  })

  it.each([
    [401, { data: null, error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } }],
    [409, { data: null, error: { code: 'WORKSPACE_CHANGED', message: 'Reload workspace' } }],
    [200, { data: null, error: { code: 'STALE_VERSION', message: 'Workspace changed' } }],
  ])('throws a typed error for status %s or an envelope error', async (status, envelope) => {
    server.use(
      http.get('http://localhost:3000/api/failure', () =>
        HttpResponse.json(envelope, { status }),
      ),
    )

    const error = await apiRequest('/api/failure').catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiClientError)
    expect(error).toMatchObject({ code: envelope.error.code, status })
  })

  it.each([
    ['non-JSON', new HttpResponse('nope', { status: 502 })],
    ['invalid JSON', HttpResponse.json({ unexpected: true })],
  ])('reports %s responses as INVALID_RESPONSE', async (_label, response) => {
    server.use(http.get('http://localhost:3000/api/invalid', () => response))

    await expect(apiRequest('/api/invalid')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
      status: response.status,
    })
  })

  it.each([
    ['warnings', { data: null, error: null, warnings: 'warning' }],
    ['workspace version', { data: null, error: null, workspace_version: 7 }],
    ['error payload', { data: null, error: { code: 'BROKEN' } }],
    ['error details', { data: null, error: { code: 'BROKEN', message: 'Broken', details: [] } }],
    ['operation id', { data: null, error: { code: 'BROKEN', message: 'Broken', operation_id: 7 } }],
  ])('reports malformed %s as INVALID_RESPONSE', async (_label, envelope) => {
    server.use(
      http.get('http://localhost:3000/api/malformed', () => HttpResponse.json(envelope)),
    )

    await expect(apiRequest('/api/malformed')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
      status: 200,
    })
  })
})
