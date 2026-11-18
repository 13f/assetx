# Development guide

## Prerequisites

- **Python 3.11+** (the project is tested with 3.13).
- **Bun 1.4+** for the frontend (`bun --version`). Bun runs Vite, installs packages, and executes the frontend scripts.
- Windows, macOS, or Linux.

## Install

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

cd frontend
bun install
```

macOS/Linux equivalents:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cd frontend && bun install
```

## Run in development

Terminal 1 — API with auto-reload:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Terminal 2 — Vite:

```powershell
cd frontend
bun run dev
```

- SPA: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000/api/health>
- API docs: <http://127.0.0.1:8000/api/docs>

Vite proxies `/api` to port 8000, so no CORS configuration is needed in dev.

## Build and run from one server

```powershell
cd frontend
bun run build
cd ..\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

FastAPI mounts `frontend/dist` at `/` when the directory contains `index.html`. API routes keep priority.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

The test suite does not call public endpoints. It injects:

- a deterministic `FakeAdapter` for balances,
- a deterministic `FakePriceService`,
- temporary SQLite files under `backend/tests/.test-data` (cleaned after each test).

Coverage includes:

- address validation for all six chains, including bech32/bech32m, c32check, and CKB lock decoding,
- seeded tokens and native symbols, including the Lido stETH and earnETH Ethereum contracts,
- tag normalization and duplicate protection,
- token registry CRUD and native-network immutability,
- queue deduplication and 3-second spacing,
- JSON-RPC fallback from a failed provider to the next,
- Uniswap V3/V4 position decoding, tick math, Keccak-256 pool ids, LP scan limits, and contract-address pricing,
- price cache completeness,
- the full refresh → balances → prices → card summary flow, including LP position persistence and totals.

Frontend checks:

```powershell
cd frontend
bun run typecheck
bun run build
```

## Configuration

Settings are read from environment variables with the `ASSETX_` prefix and from `backend/.env` (see `backend/.env.example`).

| Variable | Default | Notes |
| --- | --- | --- |
| `ASSETX_DATABASE_PATH` | `backend/data/assetx.db` | Relative paths resolve from repo root |
| `ASSETX_FRONTEND_DIST` | `frontend/dist` | Static build location |
| `ASSETX_REFRESH_INTERVAL_SECONDS` | `3` | Start-to-start spacing |
| `ASSETX_REQUEST_TIMEOUT_SECONDS` | `20` | Outbound RPC timeout |
| `ASSETX_PRICE_CACHE_SECONDS` | `15` | Complete-cache TTL |
| `ASSETX_PRICE_REQUEST_TIMEOUT_SECONDS` | `15` | Reserved price timeout |
| `ASSETX_CORS_ORIGINS` | local Vite origins | Comma separated or `*` |
| `ASSETX_START_WORKER` | `true` | Set false for API-only/testing |
| `ASSETX_ETHEREUM_RPCS` | built-in | Comma-separated ordered list |
| `ASSETX_ETHEREUM_LP_POSITIONS_ENABLED` | `true` | Scan Ethereum wallets for Uniswap LP NFTs |
| `ASSETX_ETHEREUM_LP_POSITION_MANAGERS` | built-in | Comma-separated V3 position-manager override |
| `ASSETX_ETHEREUM_LP_MAX_POSITIONS` | `30` | Position scan cap per wallet |
| `ASSETX_ETHEREUM_LP_V4_ENABLED` | `true` | Scan for Uniswap V4 positions |
| `ASSETX_ETHEREUM_LP_BLOCKSCOUT_APIS` | built-in | Comma-separated Blockscout API override |
| `ASSETX_SOLANA_RPCS` | built-in | Comma-separated ordered list |
| `ASSETX_BITCOIN_APIS` | built-in | Comma-separated ordered list |
| `ASSETX_NERVOS_RPCS` | built-in | Comma-separated ordered list |
| `ASSETX_COSMOS_APIS` | built-in | Comma-separated ordered list |
| `ASSETX_STACKS_APIS` | built-in | Comma-separated ordered list |

Runtime data lives in `backend/data/`. Delete `assetx.db*` to reset the app; tokens are re-seeded on the next start.

To populate the six public sample addresses used in the screenshots:

```powershell
python scripts\seed_demo.py
```

This only works while the API is running on `http://127.0.0.1:8000`.

## Project layout

```text
assetx/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers
│   │   ├── chains/       # chain adapters + registry
│   │   ├── services/     # refresh, prices, queue, read models
│   │   ├── utils/        # validation and encoding helpers
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── main.py
│   │   └── seed.py
│   ├── data/             # sqlite runtime files (gitignored)
│   ├── tests/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── pyproject.toml
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   ├── composables/
│   │   ├── utils/
│   │   ├── App.vue
│   │   ├── api.ts
│   │   ├── style.css
│   │   └── types.ts
│   ├── package.json
│   ├── bun.lock
│   └── vite.config.ts
├── docs/
├── README.md
└── LICENSE
```

## Frontend notes

- Vue 3 `<script setup>` and TypeScript strict mode.
- DaisyUI 5 with a custom `assetx` dark theme in `src/style.css`.
- Tailwind CSS 4 via `@tailwindcss/vite`.
- No router: the header switches between the accounts view and token registry.
- Chain summaries are computed in `App.vue` from the loaded account totals and rendered by `components/ChainCard.vue`; clicking a card toggles the same chain filter as the hero chips.
- Polling interval: 2.5 seconds while the page is visible.
- API client: `frontend/src/api.ts`; base URL defaults to `/api` and can be overridden with `VITE_API_BASE_URL`.

## Backend extension points

### Add a chain

1. Add a `ChainDefinition` in `app/chains/registry.py` with native symbol, decimals, validators, explorer URL, and provider list.
2. Add an address validator in `app/utils/validation.py`.
3. Implement a `ChainAdapter` in `app/chains/` returning a `FetchResult`.
4. Register the adapter class in `build_adapters`.
5. Add seed entries for the native token and any common token networks.
6. Update chain metadata consumers (frontend uses API metadata; chain icons need a visual entry).
7. Add tests for address validation, provider parsing, and fallback.

### Add a token

Use the UI (“Tokens” → “Add token”, then “+ Network”) or the API:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/tokens `
  -ContentType 'application/json' `
  -Body '{"symbol":"LINK","name":"Chainlink","coingecko_id":"chainlink"}'

Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/tokens/10/networks/ethereum `
  -ContentType 'application/json' `
  -Body '{"contract_address":"0x514910771AF9Ca656af840dff83E8264EcF986CA","decimals":18}'
```

### Add an LP position manager

The built-in Uniswap V3 and V4 readers run against the canonical Ethereum contracts. Additional Uniswap V3-compatible managers can be scanned without code:

```dotenv
ASSETX_ETHEREUM_LP_POSITION_MANAGERS=0xC36442b4a4522E871399CD717aBDD847Ab11FE88,0x...
```

Set `ASSETX_ETHEREUM_LP_POSITIONS_ENABLED=false` to turn Ethereum NFT discovery off, or `ASSETX_ETHEREUM_LP_V4_ENABLED=false` to skip only V4. V4 discovery needs Blockscout; set `ASSETX_ETHEREUM_LP_BLOCKSCOUT_APIS` to a self-hosted index when the public instance is rate limited. A different position protocol (for example a non-Uniswap NFT model) needs a new reader that returns `LpPosition` objects in `FetchResult.positions` and marks its protocol name in `positions_complete`; the refresh, persistence, pricing, and API layers then work unchanged.

### Change the interval

Set `ASSETX_REFRESH_INTERVAL_SECONDS` in `backend/.env` and restart the API. The queue interval is exposed to the UI through `/api/refresh/status`.

## Troubleshooting

- **`bun: command not found`** — install Bun from <https://bun.sh/> and reopen the terminal.
- **Frontend shows old UI after `bun run build`** — restart the FastAPI process or hard-refresh the browser; the static directory is mounted at startup.
- **A Lido balance is missing** — `STETH` and `EARNETH` are seeded as enabled Ethereum networks. If the network was removed or disabled, restore it from the Tokens page and refresh the address. Unclaimed Lido Earn shares and pending deposit/redeem queue requests are not part of the wallet balance.
- **A card is `partial`** — one or more positive balances or LP positions have no price. Check the token's CoinGecko id or press “Refresh prices” on the Tokens page. LP underlying tokens are priced by contract address and cannot be fixed from the registry; obscure tokens may simply have no price feed.
- **An LP position is missing** — the scan is capped by `ASSETX_ETHEREUM_LP_MAX_POSITIONS`, and the position must be owned by the wallet (not staked elsewhere). Uniswap V2 LP tokens and generic NFTs are out of scope. For V4, Blockscout must have indexed the position; check `last_refresh_warning` for `Uniswap V4` discovery errors and configure `ASSETX_ETHEREUM_LP_BLOCKSCOUT_APIS` if the public index is rate limited.
- **Solana token balances are zero with a warning** — the official public RPC is rate limiting indexed requests. Configure a private Solana RPC in `ASSETX_SOLANA_RPCS`.
- **Stacks balances fail with 429** — the Hiro API rate limits per IP. Configure a keyed endpoint in `ASSETX_STACKS_APIS`.
- **A refresh failed** — open the queue indicator to see active jobs, and `GET /api/refresh/jobs` for provider/error details. Previous balances are preserved.
- **Address rejected** — the API returns a chain-specific 422 message; check the address format on the chain documentation page.
