import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { exchangeBootstrapToken } from './api/bootstrap'
import App from './app/App'
import './styles/tokens.css'
import './styles/global.css'

function renderApp() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

function renderBootstrapFailure(error: unknown) {
  const message = error instanceof Error ? error.message : 'The desktop login exchange could not be completed.'
  createRoot(document.getElementById('root')!).render(
    <main aria-labelledby="bootstrap-error-heading" className="routeFallback" role="alert">
      <h1 id="bootstrap-error-heading">Login unavailable</h1>
      <p>{message}</p>
      <button className="button button--secondary" onClick={() => window.location.reload()} type="button">Retry login</button>
    </main>,
  )
}

exchangeBootstrapToken().then(renderApp).catch(renderBootstrapFailure)
