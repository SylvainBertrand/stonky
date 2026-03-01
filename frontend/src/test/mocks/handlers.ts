import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/health', () => {
    return HttpResponse.json({ status: 'ok', db: 'connected' })
  }),

  http.get('/api/watchlists', () => {
    return HttpResponse.json([
      { id: 1, name: 'Tech Stocks', description: 'Top technology picks', is_default: true },
      { id: 2, name: 'Dividend Growth', description: null, is_default: false },
    ])
  }),
]
