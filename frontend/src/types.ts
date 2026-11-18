export type ChainId = 'ethereum' | 'solana' | 'bitcoin' | 'nervos' | 'cosmos' | 'stacks'

export interface ChainMeta {
  id: ChainId
  name: string
  native_symbol: string
  native_name: string
  native_decimals: number
  native_coingecko_id: string
  address_placeholder: string
  address_hint: string
  supports_tokens: boolean
  token_standard: string | null
  explorer_url: string
  provider_count: number
  accent: string
}

export interface TokenBalance {
  network_id: number
  token_id: number
  symbol: string
  name: string
  chain: ChainId
  contract_address: string | null
  decimals: number
  is_native: boolean
  raw_balance: string
  balance: string
  price_usd: string | null
  value_usd: string | null
  updated_at: string
}

export interface RefreshState {
  job_id: number
  status: 'queued' | 'running'
  created_at: string
  started_at: string | null
}

export interface Account {
  id: number
  chain: ChainId
  chain_name: string
  accent: string
  address: string
  tags: string[]
  created_at: string
  last_refreshed_at: string | null
  last_refresh_error: string | null
  last_refresh_warning: string | null
  last_refresh_provider: string | null
  total_usd: string
  total_status: 'stale' | 'partial' | 'complete'
  unpriced_token_count: number
  tracked_token_count: number
  hidden_token_count: number
  tokens: TokenBalance[]
  refresh: RefreshState | null
}

export interface TokenNetwork {
  id: number
  chain: ChainId
  contract_address: string | null
  decimals: number
  is_native: boolean
  enabled: boolean
}

export interface Token {
  id: number
  symbol: string
  name: string
  coingecko_id: string | null
  created_at: string
  price_usd: string | null
  price_source: string | null
  price_updated_at: string | null
  networks: TokenNetwork[]
}

export interface RefreshJob {
  id: number
  address_id: number | null
  status: 'queued' | 'running' | 'success' | 'failed'
  trigger: string
  provider: string | null
  warning: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  chain?: ChainId | null
  address?: string | null
}

export interface QueueStatus {
  worker_running: boolean
  queue_size: number
  interval_seconds: number
  counts: {
    queued: number
    running: number
    success: number
    failed: number
  }
  active: Array<{
    id: number
    address_id: number | null
    status: 'queued' | 'running'
    created_at: string
    started_at: string | null
    chain: ChainId | null
    address: string | null
  }>
}

export interface ListResponse<T> {
  items: T[]
  total?: number
}
