import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { Toaster } from 'sonner'
import { Providers } from '@/app/providers'
import { router } from '@/app/router'
import '@/styles/globals.css'

const root = document.getElementById('root')
if (!root) throw new Error('Root element not found')

createRoot(root).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
      <Toaster richColors position="top-right" />
    </Providers>
  </StrictMode>,
)
