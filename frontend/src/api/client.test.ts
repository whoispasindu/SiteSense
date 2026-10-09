import { describe, expect, it, vi } from 'vitest'
import { jsonResponse } from '../test/renderRoute'
import { api, ApiError } from './client'

describe('api client', () => {
  it('returns the parsed JSON body on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' })))

    await expect(api.get('/health')).resolves.toEqual({ status: 'ok' })
    expect(fetch).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('sends JSON bodies with a JSON content type', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ id: 1 }, 201)))

    await api.post('/projects', { name: 'Kandy Apartments' })

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"name":"Kandy Apartments"}')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('turns the backend error shape into an ApiError', async () => {
    const body = { error: { code: 'not_found', message: 'Project not found' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body, 404)))

    const error = await api.get('/projects/99').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, code: 'not_found', message: 'Project not found' })
  })

  it('still throws an ApiError when the error body is not JSON', async () => {
    const response = new Response('Bad gateway', { status: 502, statusText: 'Bad Gateway' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(api.get('/health')).rejects.toMatchObject({ status: 502, code: 'http_error' })
  })

  it('reports a network error when the server cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(api.get('/health')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })
})
