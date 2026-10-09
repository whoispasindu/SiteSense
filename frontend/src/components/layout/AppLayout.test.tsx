import { fireEvent, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse, renderRoute } from '../../test/renderRoute'

describe('app layout', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', database: 'ok' })))
  })

  it('shows the navigation and the dashboard at /', async () => {
    renderRoute('/')

    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('shows the API and database status from the health endpoint', async () => {
    renderRoute('/')

    expect(await screen.findAllByText('Connected')).toHaveLength(2)
  })

  it('shows the not found page for unknown paths', () => {
    renderRoute('/no-such-page')

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('opens and closes the menu on small screens', () => {
    renderRoute('/')
    const menuButton = screen.getByRole('button', { name: 'Menu' })

    fireEvent.click(menuButton)
    expect(menuButton).toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(menuButton)
    expect(menuButton).toHaveAttribute('aria-expanded', 'false')
  })
})
