import { useQuery } from '@tanstack/react-query'
import { api } from './client'

/** Matches HealthResponse in backend/app/api/health.py */
export interface HealthResponse {
  status: 'ok'
  database: 'ok' | 'unavailable'
}

export const getHealth = () => api.get<HealthResponse>('/health')

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })
}
