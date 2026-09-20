import { QueryClient } from '@tanstack/react-query'
import { ApiClientError } from '../api/client'

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) =>
          !(error instanceof ApiClientError && error.status >= 400 && error.status < 500)
          && failureCount < 1,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  })
}

export const queryClient = createAppQueryClient()
