# API reference

Base URL: `http://127.0.0.1:8000/api`

Interactive docs: `http://127.0.0.1:8000/api/docs`

OpenAPI JSON: `http://127.0.0.1:8000/api/openapi.json`

All requests and responses are JSON. There is no authentication; AssetX is intended to run locally or behind your own auth reverse proxy.

## Errors

FastAPI validation errors use:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "address"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

Business errors use:

```json
{ "detail": "This address is already tracked on this chain" }
```

Common status codes: `400` unknown chain, `404` missing resource, `409` duplicate or immutable native network, `422` validation error, `202` job accepted.

## Health and metadata

### `GET /health`

```json
{ "status": "ok", "time": "2026-11-15T07:22:07Z" }
```

### `GET /chains`

```json
{
  "items": [
    {
      "id": "ethereum",
      "name": "Ethereum",
      "native_symbol": "ETH",
      "native_name": "Ether",
      "native_decimals": 18,
      "native_coingecko_id": "ethereum",
      "address_placeholder": "0x...",
      "address_hint": "EVM address: 0x followed by 40 hex characters",
      "supports_tokens": true,
      "token_standard": "ERC-20",
      "supports_nft_positions": true,
      "explorer_url": "https://etherscan.io/address/{address}",
      "provider_count": 4,
      "accent": "#627EEA"
    }
  ]
}
```

### `GET /chains/{chain}`

Returns one chain object or `404`.

### `GET /meta`

Returns `name`, `version`, `chains`, `refresh_interval_seconds`, and the seeded symbol list.

## Addresses

### `GET /addresses`

Optional query params: `chain`, `tag`, `q` (matches address or tags).

```json
{
  "items": [
    {
      "id": 1,
      "chain": "ethereum",
      "chain_name": "Ethereum",
      "accent": "#627EEA",
      "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
      "tags": ["defi", "whale"],
      "created_at": "2026-11-15T07:28:35Z",
      "last_refreshed_at": "2026-11-15T07:29:34Z",
      "last_refresh_error": null,
      "last_refresh_warning": null,
      "last_refresh_provider": "ethereum-rpc.publicnode.com",
      "total_usd": "10763.01",
      "total_status": "complete",
      "unpriced_token_count": 0,
      "unpriced_position_count": 0,
      "tracked_token_count": 5,
      "hidden_token_count": 0,
      "position_count": 1,
      "tokens": [
        {
          "network_id": 1,
          "token_id": 1,
          "symbol": "ETH",
          "name": "Ether",
          "chain": "ethereum",
          "contract_address": null,
          "decimals": 18,
          "is_native": true,
          "raw_balance": "5798969845714110716",
          "balance": "5.798969845714110716",
          "price_usd": "1790.328271",
          "value_usd": "10382.06",
          "updated_at": "2026-11-15T07:29:34Z"
        }
      ],
      "positions": [
        {
          "id": 1,
          "protocol": "uniswap-v3",
          "collection": "Uniswap V3",
          "contract_address": "0xc36442b4a4522e871399cd717abdd847ab11fe88",
          "token_id": "112161",
          "pool_address": "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
          "fee_tier": 500,
          "tick_lower": -887220,
          "tick_upper": 887220,
          "in_range": true,
          "liquidity": "137378032570732",
          "token0": {
            "address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "symbol": "WETH",
            "decimals": 18,
            "amount": "0.1",
            "price_usd": "1809.948603",
            "value_usd": "180.99"
          },
          "token1": {
            "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "symbol": "USDC",
            "decimals": 6,
            "amount": "200",
            "price_usd": "0.9998188845",
            "value_usd": "199.96"
          },
          "value_usd": "380.95",
          "updated_at": "2026-11-15T07:29:34Z"
        }
      ],
      "refresh": null
    }
  ],
  "total": 1
}
```

`total_status`:

- `stale` — never refreshed.
- `partial` — at least one positive balance or LP position has no USD price.
- `complete` — refreshed and all positive balances and positions are priced.

`tokens` on the list endpoint is capped at 3. `GET /addresses/{id}` returns every saved balance and LP position. `refresh` is non-null when a job is queued/running.

`positions` is populated for Ethereum wallets that own Uniswap V3 or V4 LP NFTs (see [chains](chains.md#uniswap-lp-positions-v3-and-v4-nfts)). A position's `token0`/`token1` amounts are already converted to human units from the position's on-chain liquidity and price range. `protocol` is `uniswap-v3` or `uniswap-v4`; `pool_address` is the V3 pool address or the V4 `bytes32` pool id. A V4 position can hold native ETH, which is reported with the zero address and the `ETH` symbol. `in_range` compares the current pool tick with `[tick_lower, tick_upper)`. `value_usd` is `null` when a side with a positive amount has no contract price; such a position still appears, and `unpriced_position_count` is non-zero. `position_count` is the total saved position count.

### `POST /addresses`

```json
{
  "chain": "ethereum",
  "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "tags": ["DeFi", "Cold Wallet"]
}
```

- `chain` is required and must be one of the six chain ids.
- The address is validated and normalized per chain; EVM addresses are lowercased, Stacks c32check addresses are uppercased.
- Tags are trimmed, whitespace collapsed, lowercased, de-duplicated, and limited to 10 by default.
- Returns `201` with the account. Duplicate `(chain, address)` returns `409`.

### `PATCH /addresses/{id}`

```json
{ "tags": ["whale", "defi"] }
```

Replaces the tag list. Returns the updated full account.

### `DELETE /addresses/{id}`

`204`. Cascades saved balances and refresh jobs. Does not affect the wallet.

### `POST /addresses/{id}/refresh`

Queues a refresh. Returns `202`:

```json
{
  "job": {
    "job_id": 42,
    "status": "queued",
    "created_at": "2026-11-15T07:30:00Z",
    "deduplicated": false
  },
  "status": {
    "worker_running": true,
    "queue_size": 1,
    "interval_seconds": 3,
    "counts": { "queued": 1, "running": 0, "success": 8, "failed": 0 },
    "active": []
  }
}
```

If a job is already queued/running for this address, the existing job is returned with `deduplicated: true`.

### `POST /addresses/refresh-all`

Queues every address. Returns `202` with `jobs`, `count`, and current queue `status`. Existing active jobs are deduplicated.

## Refresh queue

### `GET /refresh/status`

```json
{
  "worker_running": true,
  "queue_size": 0,
  "interval_seconds": 3,
  "counts": { "queued": 0, "running": 0, "success": 12, "failed": 1 },
  "active": [
    {
      "id": 42,
      "address_id": 1,
      "status": "running",
      "created_at": "2026-11-15T07:30:00Z",
      "started_at": "2026-11-15T07:30:03Z",
      "chain": "ethereum",
      "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
    }
  ]
}
```

`counts` cover all historical jobs in the database. `active` contains only queued/running jobs.

### `GET /refresh/jobs?limit=20`

Returns the newest jobs with `status`, `provider`, `warning`, `error`, `created_at`, `started_at`, `finished_at`, and `duration_ms`.

## Token registry

### `GET /tokens`

```json
{
  "items": [
    {
      "id": 1,
      "symbol": "ETH",
      "name": "Ether",
      "coingecko_id": "ethereum",
      "created_at": "2026-11-15T07:20:00Z",
      "price_usd": "1790.328271",
      "price_source": "defillama",
      "price_updated_at": "2026-11-15T07:29:34Z",
      "networks": [
        {
          "id": 1,
          "chain": "ethereum",
          "contract_address": null,
          "decimals": 18,
          "is_native": true,
          "enabled": true
        }
      ]
    }
  ]
}
```

### `POST /tokens`

```json
{
  "symbol": "LINK",
  "name": "Chainlink",
  "coingecko_id": "chainlink"
}
```

Creates a registry entry with no networks. `201`; duplicate symbol `409`.

### `PATCH /tokens/{id}`

```json
{ "name": "Chainlink", "coingecko_id": "chainlink" }
```

Set `coingecko_id` to `null` to clear it and stop pricing the token.

### `PUT /tokens/{id}/networks/{chain}`

```json
{
  "contract_address": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
  "decimals": 18,
  "enabled": true
}
```

- Ethereum: ERC-20 contract address.
- Solana: SPL mint address.
- Cosmos: bank denom (for example `uatom` or `ibc/...`).
- Stacks: full SIP-010 asset id (`<contract-principal>::<asset-name>`, for example `SP....my-token::my-token`). A bare contract principal is rejected.
- Bitcoin and Nervos: `400`, generic token contracts are not supported by AssetX.
- Native networks are immutable (`409`).
- Changing a contract deletes old balance rows for that network.
- Setting `enabled` to `false` keeps the row but excludes it from refreshes.

### `DELETE /tokens/{id}/networks/{chain}`

`204`. Native network deletion returns `409`.

### `DELETE /tokens/{id}`

`204`. Native tokens cannot be deleted (`409`). Other tokens cascade their networks, balances, and price cache.

### `POST /tokens/prices/refresh`

Forces a price refresh for every token with a `coingecko_id`.

```json
{
  "updated": 9,
  "source": "defillama",
  "fetched_at": "2026-11-15T07:29:11Z",
  "warning": null,
  "prices": { "ETH": "1790.684582", "BTC": "64336.425494" }
}
```

## Examples

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/chains

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/addresses `
  -ContentType 'application/json' `
  -Body '{"chain":"bitcoin","address":"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa","tags":["Genesis"]}'

Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/addresses/1/refresh

Invoke-RestMethod http://127.0.0.1:8000/api/refresh/status
```

curl:

```bash
curl http://127.0.0.1:8000/api/health
curl -X POST http://127.0.0.1:8000/api/addresses \
  -H 'Content-Type: application/json' \
  -d '{"chain":"solana","address":"9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM","tags":["hot wallet"]}'
curl -X POST http://127.0.0.1:8000/api/addresses/refresh-all
```
