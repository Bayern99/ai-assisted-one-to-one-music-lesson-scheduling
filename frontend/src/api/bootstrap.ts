import { apiRequest } from './client'

let inFlight: Promise<void> | null = null

export function exchangeBootstrapToken(): Promise<void> {
  if (inFlight) {
    return inFlight
  }

  const initialUrl = new URL(window.location.href)
  if (!initialUrl.searchParams.has('bootstrap')) {
    return Promise.resolve()
  }

  const token = initialUrl.searchParams.get('bootstrap') ?? ''
  const historyState = window.history.state
  const exchange = (async () => {
    try {
      if (token) {
        await apiRequest('/api/auth/exchange', {
          method: 'POST',
          headers: { 'X-PI-Bootstrap-Token': token },
        })
      }
    } finally {
      initialUrl.searchParams.delete('bootstrap')
      window.history.replaceState(
        historyState,
        '',
        `${initialUrl.pathname}${initialUrl.search}${initialUrl.hash}`,
      )
    }
  })()
  inFlight = exchange
  const clearInFlight = () => {
    if (inFlight === exchange) {
      inFlight = null
    }
  }
  void exchange.then(clearInFlight, clearInFlight)
  return exchange
}
