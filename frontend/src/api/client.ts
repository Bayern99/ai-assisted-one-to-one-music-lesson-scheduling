import type { components } from './schema'

export type ApiErrorPayload = components['schemas']['ApiErrorPayload']

type GeneratedEnvelope = components['schemas']['ApiEnvelope_dict_str__bool__']
type WireEnvelope<T> = Omit<GeneratedEnvelope, 'data'> & { data?: T | null }

export interface ApiEnvelope<T> {
  data: T | null
  workspace_version: string | null
  warnings: string[]
  error: ApiErrorPayload | null
}

const invalidResponse: ApiErrorPayload = {
  code: 'INVALID_RESPONSE',
  message: 'The local API returned an invalid response',
}

export class ApiClientError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown> | null
  readonly operationId: string | null

  constructor(status: number, error: ApiErrorPayload) {
    super(error.message)
    this.name = 'ApiClientError'
    this.code = error.code
    this.status = status
    this.details = error.details ?? null
    this.operationId = error.operation_id ?? null
  }
}

function isWireEnvelope(value: unknown): value is WireEnvelope<unknown> {
  if (!value || typeof value !== 'object') {
    return false
  }

  const envelope = value as Record<string, unknown>
  if (!['data', 'workspace_version', 'warnings', 'error'].some((key) => key in envelope)) {
    return false
  }

  const error = envelope.error
  const errorPayload = error as Record<string, unknown>
  if (
    'error' in envelope
    && error !== null
    && (
      typeof error !== 'object'
      || typeof errorPayload.code !== 'string'
      || typeof errorPayload.message !== 'string'
      || ('details' in errorPayload
        && errorPayload.details !== null
        && (typeof errorPayload.details !== 'object' || Array.isArray(errorPayload.details)))
      || ('operation_id' in errorPayload
        && errorPayload.operation_id !== null
        && typeof errorPayload.operation_id !== 'string')
    )
  ) {
    return false
  }

  return (
    (!('workspace_version' in envelope)
      || envelope.workspace_version === null
      || typeof envelope.workspace_version === 'string')
    && (!('warnings' in envelope)
      || (Array.isArray(envelope.warnings) && envelope.warnings.every((item) => typeof item === 'string')))
  )
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers)
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers,
  })

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ApiClientError(response.status, invalidResponse)
  }

  if (!isWireEnvelope(payload)) {
    throw new ApiClientError(response.status, invalidResponse)
  }

  const envelope: ApiEnvelope<T> = {
    data: (payload.data as T | null | undefined) ?? null,
    workspace_version: payload.workspace_version ?? null,
    warnings: payload.warnings ?? [],
    error: payload.error ?? null,
  }
  if (!response.ok || envelope.error) {
    throw new ApiClientError(response.status, envelope.error ?? invalidResponse)
  }
  return envelope
}
