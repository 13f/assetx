import type {
  Account,
  ChainMeta,
  ListResponse,
  QueueStatus,
  RefreshJob,
  Token,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function detailFromPayload(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return 'Request failed'
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const where = 'loc' in item && Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
          return where ? `${where}: ${String(item.msg)}` : String(item.msg)
        }
        return String(item)
      })
      .join('; ')
  }
  return 'Request failed'
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers ?? {}),
      },
    })
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? `Network error: ${error.message}` : 'Network error',
      0,
    )
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    throw new ApiError(detailFromPayload(payload), response.status)
  }
  return payload as T
}

export const api = {
  meta: () => request<{ name: string; version: string; chains: ChainMeta[] }>('/meta'),
  chains: () => request<ListResponse<ChainMeta>>('/chains'),

  accounts: () => request<ListResponse<Account>>('/addresses'),
  account: (id: number) => request<Account>(`/addresses/${id}`),
  createAccount: (body: { chain: string; address: string; tags: string[] }) =>
    request<Account>('/addresses', { method: 'POST', body: JSON.stringify(body) }),
  updateTags: (id: number, tags: string[]) =>
    request<Account>(`/addresses/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ tags }),
    }),
  deleteAccount: (id: number) =>
    request<void>(`/addresses/${id}`, { method: 'DELETE' }),
  refreshAccount: (id: number) =>
    request<{ job: { job_id: number; status: string; deduplicated: boolean } }>(
      `/addresses/${id}/refresh`,
      { method: 'POST' },
    ),
  refreshAll: () =>
    request<{ count: number; jobs: unknown[] }>('/addresses/refresh-all', {
      method: 'POST',
    }),

  queueStatus: () => request<QueueStatus>('/refresh/status'),
  jobs: (limit = 20) => request<ListResponse<RefreshJob>>(`/refresh/jobs?limit=${limit}`),

  tokens: () => request<ListResponse<Token>>('/tokens'),
  refreshPrices: () =>
    request<{ updated: number; source: string | null; warning: string | null }>(
      '/tokens/prices/refresh',
      { method: 'POST' },
    ),
  createToken: (body: { symbol: string; name: string; coingecko_id?: string | null }) =>
    request<Token>('/tokens', { method: 'POST', body: JSON.stringify(body) }),
  updateToken: (id: number, body: { name?: string; coingecko_id?: string | null }) =>
    request<Token>(`/tokens/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteToken: (id: number) => request<void>(`/tokens/${id}`, { method: 'DELETE' }),
  upsertNetwork: (
    tokenId: number,
    chain: string,
    body: { contract_address: string; decimals: number; enabled?: boolean },
  ) =>
    request<Token>(`/tokens/${tokenId}/networks/${chain}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteNetwork: (tokenId: number, chain: string) =>
    request<void>(`/tokens/${tokenId}/networks/${chain}`, { method: 'DELETE' }),
}
