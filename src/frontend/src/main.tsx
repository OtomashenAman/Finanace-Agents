import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { sessionSlot } from './lib/session-slot'

// Pick this tab's session first: a tab opened as another user carries it in the URL, which is
// cleaned before the router reads it
sessionSlot()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
