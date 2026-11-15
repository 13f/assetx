# Architecture

AssetX is intentionally small: a static Vue SPA, a FastAPI process, one SQLite database, one background refresh worker, and outbound calls to public chain/price APIs.

```text
┌────────────────────────────┐        HTTP/JSON        ┌────────────────────────────────────┐
│  Vue 3 + Vite + DaisyUI    │  ───────────────────▶  │  FastAPI                           │
│  frontend/src              │  ◀───────────────────  │  backend/app                       │
└────────────────────────────┘                         │                                    │
                                                       │  ┌──────────────────────────────┐  │
                                                       │  │ RefreshQueue (1 worker)      │  │
                                                       │  │ 3s between address starts    │  │
                                                       │  └──────────────┬───────────────┘  │
                                                       │                 │                  │
                                                       │  ┌──────────────▼───────────────┐  │
                                                       │  │ RefreshService               │  │
                                                       │  │ balances + prices + persist  │  │
                                                       │  └───────┬──────────────┬───────┘  │
                                                       │          │              │          │
                                                       │  ┌───────▼───────┐  ┌───▼────────┐ │
                                                       │  │ ChainAdapter  │  │PriceService│ │
                                                       │  │ RPC failover  │  │LLama→CG    │ │
                                                       │  └───────┬───────┘  └───┬────────┘ │
                                                       └──────────┼──────────────┼──────────┘
                                                                  │              │
                                              public RPC / REST   │              │  DefiLlama /
                                              Ethereum · Solana   │              │  CoinGecko
                                              Bitcoin · Nervos    │              │
                                              Cosmos              │              │
                                                                  ▼              ▼
                                                       ┌──────────────────────────────┐
                                                       │ SQLite (WAL)                 │
                                                       │ backend/data/assetx.db       │
                                                       └──────────────────────────────┘
```

## Backend layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI factory, lifespan, static SPA mount, app state |
| `app/config.py` | Pydantic settings and env overrides |
| `app/db.py` | SQLite schema and connection/transaction wrapper |
| `app/seed.py` | Built-in native/common tokens and their networks |
| `app/api/*.py` | Meta, addresses, tokens, refresh queue routes |
| `app/chains/*.py` | Per-chain balance adapters and registry |
| `app/services/refresh.py` | Full address refresh and persistence |
| `app/services/prices.py` | Price provider fallback and cache |
| `app/services/queue.py` | Durable job queue and sequential worker |
| `app/services/repository.py` | Read models for cards, details, registry |
| `app/utils/*` | Bech32/base58/CKB validation, amounts, tags, time |

The API routes are synchronous functions for SQLite reads/writes. The refresh worker runs as an asyncio task inside the FastAPI lifespan and calls async chain/price adapters.

## SQLite model

```text
tokens ──< token_networks ──< balances >── addresses
   │              │
   └──< prices    └──< refresh_jobs (address_id)
```

| Table | Key fields | Notes |
| --- | --- | --- |
| `tokens` | `id`, `symbol`, `name`, `coingecko_id` | Symbol is unique case-insensitively |
| `token_networks` | `id`, `token_id`, `chain`, `contract_address`, `decimals`, `is_native` | Unique `(token_id, chain)`; one row per chain for a token |
| `addresses` | `id`, `chain`, `address`, `tags`, `last_refreshed_at`, `last_refresh_error`, warning/provider fields | Unique `(chain, address)` |
| `balances` | `address_id`, `token_network_id`, `raw_balance`, `price_usd`, `value_usd`, `updated_at` | Latest snapshot only; unique address+network |
| `prices` | `token_id`, `price_usd`, `source`, `fetched_at` | Shared short-lived price cache |
| `refresh_jobs` | `status`, `trigger`, `provider`, `warning`, `error`, `started_at`, `finished_at` | Audit trail and active-job dedupe |

A partial unique index ensures one active (`queued` or `running`) job per address:

```sql
CREATE UNIQUE INDEX idx_refresh_jobs_active
ON refresh_jobs(address_id)
WHERE status IN ('queued', 'running');
```

Tags are stored as a JSON array after normalization. Filters run in Python because the data volume is small and the query stays portable.

Amounts are stored as integer base units in `raw_balance` (TEXT) and converted with `Decimal`, never floats. `value_usd` is a 2-decimal string. Prices are string decimals.

## Refresh pipeline

1. `POST /api/addresses/{id}/refresh` inserts a `queued` job. If an active job exists, the same job is returned (`deduplicated: true`).
2. `RefreshQueue` puts the job id on an in-process `asyncio.Queue`.
3. The single worker waits until `interval_seconds` has elapsed since the last **address start**. Default: 3 seconds.
4. The worker marks the job `running`.
5. `RefreshService` loads all enabled token networks for the address's chain (native plus configured contracts).
6. The chain adapter tries each public endpoint in order until one returns a complete result.
7. `PriceService` loads fresh prices for the token ids; it only reuses the cache when **every** requested token has a fresh price. It falls back from DefiLlama to CoinGecko, then to stale cached prices with a warning.
8. In one SQLite transaction:
   - delete balances for token networks removed from the chain,
   - upsert a balance row for every configured network,
   - update the price cache rows,
   - set `last_refreshed_at`, `last_refresh_warning`, `last_refresh_provider`, and clear `last_refresh_error`.
9. The job is marked `success` with provider, warning, duration, and finish time.

On failure:

- The job is marked `failed` with a message.
- The address keeps its previous balances and previous `last_refreshed_at`.
- `last_refresh_error` is set; the card shows a warning icon.
- The worker continues with the next job.

On restart:

- `running` jobs are marked failed with "Interrupted by server restart".
- `queued` jobs are put back on the in-process queue.

Token-level warnings (for example a Solana indexed request being rate limited) do not fail the whole refresh; the affected token is written as zero with a warning, and other balances are still saved.

## RPC failover

Each adapter owns an ordered provider list from `app/chains/registry.py`. A provider override can be supplied with `ASSETX_<CHAIN>_RPCS`.

| Chain | Strategy |
| --- | --- |
| Ethereum | One JSON-RPC batch: `eth_getBalance` plus one `eth_call` (`balanceOf`) per ERC-20. On transport/HTTP/native error, try next RPC. |
| Solana | Sequential JSON-RPC: native balance, then one `getTokenAccountsByOwner` per mint. A provider with failed token calls is only returned if no provider produced a complete result. One short retry per token handles transient 429s. |
| Bitcoin | REST `/address/{address}` on Blockstream, then mempool.space. Confirmed plus mempool delta, clamped at zero. |
| Nervos | Decode CKB bech32/bech32m address to lock script, then `get_cells_capacity` against the indexer RPC. |
| Cosmos | Paginated `/cosmos/bank/v1beta1/balances/{address}` REST, matched against the native `uatom` denom or configured bank denoms. |

## Price pipeline

- Provider order: `https://coins.llama.fi/prices/current/` → CoinGecko `simple/price`.
- One request covers all unique CoinGecko ids in the refresh.
- Cache TTL defaults to 15 seconds. This prevents a "refresh all" batch from repeating the same price request for every address.
- A partial cache hit is not accepted: missing prices trigger a full fetch. This avoids silently unpriced assets after refreshing a chain with a different token set.
- If both providers fail, stale cached prices are used with a warning. Totals become `partial` if a positive balance has no USD price.

## Frontend behavior

- On load: fetch chains, addresses, and queue status.
- Poll queue status every 2.5 seconds; when the active count reaches zero, reload cards and show a completion toast.
- Cards display positive assets, sorted by USD value. If every balance is zero, the native token row is shown. Only three rows are rendered; the rest are available in the details modal.
- Add/Edit Tags modals validate quickly on the client and surface API errors.
- The token registry view supports custom tokens, per-chain contracts, editing, and price refresh.

## Security and privacy

- Read-only public address tracking; no seed phrases, private keys, signatures, or transactions.
- No authentication because this is designed for local/self-hosted use. Do not expose the API to the public Internet without adding auth and rate limiting.
- Outbound requests go only to configured public endpoints.
- SQLite file contains public addresses and balances, not secrets.
- CORS defaults to the local Vite dev origins. Set `ASSETX_CORS_ORIGINS=*` only if needed.
