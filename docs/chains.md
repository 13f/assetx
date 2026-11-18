# Chains, tokens and public endpoints

AssetX tracks six chains. Each address belongs to exactly one chain, and each chain has its own native asset, address format, token model, and endpoint list.

## Overview

| Chain | Native | Decimals | Address format | Token support | Default endpoints |
| --- | --- | --- | --- | --- | --- |
| Ethereum | ETH | 18 | `0x` + 40 hex | ERC-20 + Lido stETH/earnETH + Uniswap V3/V4 LP NFTs | PublicNode, dRPC, 1RPC, LlamaRPC |
| Solana | SOL | 9 | 32-byte base58 | SPL token mints | Solana mainnet-beta, PublicNode |
| Bitcoin | BTC | 8 | Base58Check or bech32/bech32m | Native only | Blockstream, mempool.space |
| Nervos | CKB | 8 | CKB bech32/bech32m | Native only | mainnet.ckb.dev, mainnet.ckbapp.dev |
| Cosmos | ATOM | 6 | `cosmos1...` bech32 | Cosmos SDK bank denoms | PublicNode, Cosmos Directory, Polkachu |
| Stacks | STX | 6 | c32check `SP...` / `SM...` | SIP-010 asset ids | Hiro API (two hosts) |

## Ethereum

- Native balance: `eth_getBalance`.
- ERC-20 balance: batched `eth_call` to `balanceOf(address)` using selector `0x70a08231`.
- Batch order is preserved by JSON-RPC ids. The first endpoint that returns a usable native result wins.
- If one ERC-20 call fails (bad contract or no code), that token is saved as zero with a warning, while other balances are still persisted.
- Address validation accepts `0x` + 40 hex. Mixed-case EIP-55 checksums are accepted; addresses are normalized to lowercase.

### Lido assets (stETH and earnETH)

Two Lido assets on Ethereum are seeded and enabled by default. Both are ordinary ERC-20 balances, so the adapter reads them in the same batched `balanceOf` round as the other configured tokens; no extra endpoint or indexer is involved.

| Asset | Contract | Decimals | CoinGecko price id |
| --- | --- | --- | --- |
| stETH (Lido Staked Ether) | `0xae7ab96520de3a18e5e111b5eaab095312d7fe84` | 18 | `staked-ether` |
| earnETH (Lido Earn ETH) | `0xbbfc8683c8fe8cf73777fede7ab9574935fea0a4` | 18 | `lido-earn-eth` |

- `stETH` is a rebasing token. `balanceOf` returns the current stETH amount, including staking rewards accrued up to the refreshed block. Each refresh stores a snapshot, so later rewards appear as a larger balance rather than as a separate rewards line.
- `earnETH` is the ERC-20 share token issued by the Lido Earn ETH vault's ShareManager (the token contract is `0xbbfc...`; the vault itself is `0x6a37...`). A wallet holds a share count that does not rebase; the per-share value grows with the vault's ETH-denominated NAV. DefiLlama and CoinGecko quote `earnETH` per share, so `balance × price` yields the USD value.
- Only the share token held by the wallet is tracked. Shares that are still claimable in the ShareManager, pending deposit requests, and redeem requests queued for withdrawal are out of scope. `wstETH` is not seeded; add it from the Tokens page if needed.

### Uniswap LP positions (V3 and V4 NFTs)

Uniswap V3 liquidity positions are ERC-721 tokens owned by the canonical `NonfungiblePositionManager` at `0xC36442b4a4522E871399CD717aBDD847Ab11FE88`. Uniswap V4 positions are ERC-721 tokens in the singleton `PositionManager` at `0xbd216513D74c8cf14cf4747E6AaA6420FF64ee9e`. AssetX treats both as a separate, non-fungible holding type; they are not mixed into the ERC-20 balance list. Every saved row records its `protocol`: `uniswap-v3` or `uniswap-v4`.

V3 discovery and decoding, in one scan per wallet:

1. `balanceOf(owner)` on the position manager, then `tokenOfOwnerByIndex(owner, i)` for each index (ERC-721 Enumerable). Duplicate token ids are dropped.
2. `positions(tokenId)` returns the token pair, fee tier, tick range, and liquidity.
3. `factory()` on the position manager, then `getPool(token0, token1, fee)`, then the pool's `slot0()` for the current `sqrtPriceX96` and tick.
4. `symbol()` and `decimals()` on both underlying ERC-20s.

V4 discovery and decoding:

- The V4 position manager is ERC-721 but **not ERC-721 Enumerable**, so `tokenOfOwnerByIndex` is not available. AssetX asks a public Blockscout NFT index (`GET /api/v2/addresses/{address}/nft?type=ERC-721`) for the ERC-721 ids owned by the wallet and filters them to the V4 position manager. This is the only indexer dependency; the base URL is configurable and can be a self-hosted instance.
- `ownerOf(tokenId)` is checked on-chain so an id that the index has not yet caught up with after a transfer is discarded.
- `getPoolAndPositionInfo(tokenId)` returns the full `PoolKey` (currency0, currency1, fee, tickSpacing, hooks) and the packed `PositionInfo` (tickLower, tickUpper, poolId prefix).
- `getPositionLiquidity(tokenId)` returns the current liquidity.
- `poolId = keccak256(abi.encode(PoolKey))`, then `StateView.getSlot0(poolId)` returns the current `sqrtPriceX96`, tick, protocol fee, and dynamic `lpFee`.
- Native ETH is the zero address in a `PoolKey`; it is priced from the chain's native token in the registry. ERC-20 currencies are priced by contract address.
- V4 positions can use a dynamic fee. The displayed fee is the current `lpFee` from `slot0`; a static pool reports its configured fee.

Underlying amounts for both versions use Uniswap's concentrated-liquidity relations (whitepaper 6.29/6.30). A position holds only token0 below the range, only token1 above it, and a mix inside it. `in_range` is `tickLower <= currentTick < tickUpper`.

Valuation:

- Each side is converted to human units with its own decimals and priced through DefiLlama (`ethereum:0x...`) with a CoinGecko `simple/token_price` fallback. Native ETH uses the native token price. Underlying tokens are not added to the curated token registry.
- A position with a positive, unpriced side is saved with `value_usd = null`; the account total is then marked `partial`.
- `contract_prices` caches address-based prices for the same short TTL as registry prices.

Limits and scope:

- The scan is capped at `ASSETX_ETHEREUM_LP_MAX_POSITIONS` positions per wallet (default 30), shared by V3 and V4. Additional positions produce a warning.
- Uncollected fees (`tokensOwed`) are not included in the position value.
- Uniswap V2 LP tokens are ERC-20s, not NFTs, and are not detected automatically. Generic NFTs and positions staked in other contracts are out of scope: a staked position is held by the staking contract, not by the wallet, so an owner scan cannot see it.
- If a V3 scan fails on every endpoint, the fungible balances are still saved, the refresh records a warning, and previously saved V3 positions are kept. V4 completeness is tracked independently, so a V4 indexer outage never deletes saved V3 positions and vice versa.
- If the Blockscout index is unavailable, V4 discovery is skipped with a warning and saved V4 positions are kept. Discovery is retried after a short cooldown instead of on every Ethereum refresh.
- If a scan is partial (some position or metadata reads fail), that protocol's saved position set is also kept. Only a fully complete scan replaces it.

Configuration:

```dotenv
ASSETX_ETHEREUM_LP_POSITIONS_ENABLED=true
# Optional: comma-separated Uniswap V3-compatible position managers.
ASSETX_ETHEREUM_LP_POSITION_MANAGERS=
ASSETX_ETHEREUM_LP_MAX_POSITIONS=30
ASSETX_ETHEREUM_LP_V4_ENABLED=true
# Optional: comma-separated Blockscout-compatible API hosts.
ASSETX_ETHEREUM_LP_BLOCKSCOUT_APIS=https://eth.blockscout.com
```

Default endpoints, in order:

1. `https://ethereum-rpc.publicnode.com`
2. `https://eth.drpc.org`
3. `https://1rpc.io/eth`
4. `https://eth.llamarpc.com`

## Solana

- Native balance: `getBalance`.
- SPL balances: one `getTokenAccountsByOwner` call per configured mint, using `jsonParsed` encoding, summing every token account for that mint.
- Solana's official public endpoint rate limits aggressively. AssetX tries it first and retries a single failed token call after 250 ms.
- `solana-rpc.publicnode.com` supports native `getBalance`, but its indexed `getTokenAccountsByOwner` requires a personal token. It is therefore a native-balance fallback; if the primary endpoint is rate limited, token balances may be saved as zero with a warning. Configure your own Solana RPC for reliable SPL balances.
- Stake accounts and vote accounts are not included; only liquid wallet balances.
- Address validation requires base58 that decodes to exactly 32 bytes.

Default endpoints, in order:

1. `https://api.mainnet-beta.solana.com`
2. `https://solana-rpc.publicnode.com`

## Bitcoin

- Balance source: `GET /address/{address}` on Blockstream or mempool.space.
- Calculation: `funded_txo_sum - spent_txo_sum + mempool_funded_txo_sum - mempool_spent_txo_sum`, clamped at zero. The result includes the current mempool delta.
- Only native BTC is tracked. BRC-20, Runes, Ordinals and other meta-protocols need an indexer and are out of scope.
- Address validation:
  - Base58Check P2PKH (`1...`) and P2SH (`3...`) on mainnet.
  - SegWit `bc1...` with bech32 for v0 and bech32m for v1+.
  - Testnet addresses are rejected.

Default endpoints, in order:

1. `https://blockstream.info/api`
2. `https://mempool.space/api`

## Nervos

- AssetX decodes the CKB address into its lock script and calls the CKB indexer RPC method `get_cells_capacity` with `script_type: "lock"`.
- Supports full payload addresses (bech32m), short payload addresses (bech32), and legacy full payloads. Known short code hashes are secp256k1, multisig, and anyone-can-pay.
- Capacity is returned in shannons; `decimals = 8` gives CKB.
- Only native CKB is tracked. Generic UDT (user-defined token) balances are out of scope because they require a type-script aware indexer and a different cell model.
- Address validation uses bech32/bech32m with the `ckb` HRP and validates the lock payload.

Default endpoints, in order:

1. `https://mainnet.ckb.dev/rpc`
2. `https://mainnet.ckbapp.dev/rpc`

## Cosmos

- AssetX targets **Cosmos Hub** (`cosmoshub-4`), not every Cosmos SDK chain.
- Native balance uses the `uatom` bank denom (`decimals = 6`).
- `GET /cosmos/bank/v1beta1/balances/{address}` is paginated up to 10 pages of 1000 entries.
- Additional tokens are configured with a Cosmos bank denom. This can be a native denom or an IBC denom such as `ibc/...`.
- Staked, unbonding, and rewards balances are not included; only liquid bank balances.
- Address validation requires bech32 with the `cosmos` HRP and a 20- or 32-byte payload.

Default endpoints, in order:

1. `https://cosmos-rest.publicnode.com`
2. `https://rest.cosmos.directory/cosmoshub`
3. `https://cosmos-api.polkachu.com`

## Stacks

- AssetX targets Stacks mainnet.
- Balance source: `GET /extended/v1/address/{principal}/balances` on the Hiro Stacks API. One request returns the native STX balance plus every SIP-010 fungible token the principal holds.
- Native balance: the `stx.balance` field, in micro-STX (`decimals = 6`). Stacked STX stays in the wallet and is therefore included; mempool deltas are not applied.
- SIP-010 balances: matched by the full asset id `<contract-principal>::<asset-name>`, for example `SP2DBFGMT7SATSJPCCA38SDDPBNNQ86QWADJ3E6WT.btc-v4::btc-v4`. A wallet that does not hold the configured asset is saved as zero.
- A configured Stacks token needs the full asset id, not just the contract principal. The registry rejects an identifier without `::asset-name`.
- The registry seeds **sBTC** as a SIP-010 asset: `SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token`, 8 decimals, priced with CoinGecko id `sbtc-2`. The protocol-internal `sbtc-token-locked` asset is not tracked.
- NFTs, non-SIP-010 tokens, and contract-principal accounts are out of scope. Only wallet addresses (`SP...` single-sig, `SM...` multisig) can be tracked.
- Address validation: c32check decoding with a version byte (22 for `SP`, 20 for `SM`), a 20-byte hash160 payload, and a 4-byte double-SHA256 checksum. Testnet versions (`ST...`, `SN...`) are rejected. Input is normalized to uppercase and Crockford aliases (`O`→`0`, `I`/`L`→`1`) are accepted.

Default endpoints, in order:

1. `https://api.hiro.so`
2. `https://api.mainnet.hiro.so`

Both hosts are operated by Hiro. They share infrastructure and rate limits; set `ASSETX_STACKS_APIS` to a keyed or private endpoint for heavy usage.

## Seeded token registry

The database is seeded on first run. Later releases add new built-in tokens through versioned seed steps, so an existing database receives STX, sBTC, stETH, and earnETH on upgrade without re-adding tokens you deleted. Native tokens cannot be deleted or have their native network edited.

| Symbol | Name | Chain | Identifier | Decimals |
| --- | --- | --- | --- | --- |
| ETH | Ether | Ethereum | native | 18 |
| SOL | Solana | Solana | native | 9 |
| BTC | Bitcoin | Bitcoin | native | 8 |
| CKB | Nervos Network | Nervos | native | 8 |
| ATOM | Cosmos Hub | Cosmos | native (`uatom`) | 6 |
| STX | Stacks | Stacks | native | 6 |
| SBTC | sBTC | Stacks | `SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token` | 8 |
| USDT | Tether USD | Ethereum | `0xdac17f958d2ee523a2206206994597c13d831ec7` | 6 |
| USDT | Tether USD | Solana | `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB` | 6 |
| USDC | USD Coin | Ethereum | `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` | 6 |
| USDC | USD Coin | Solana | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | 6 |
| PAXG | PAX Gold | Ethereum | `0x45804880de22913dafe09f4980848ece6ecbaf78` | 18 |
| XAUT | Tether Gold | Ethereum | `0x68749665ff8d2d112fa859aa293f07a622782f38` | 6 |
| STETH | Lido Staked Ether | Ethereum | `0xae7ab96520de3a18e5e111b5eaab095312d7fe84` | 18 |
| EARNETH | Lido Earn ETH | Ethereum | `0xbbfc8683c8fe8cf73777fede7ab9574935fea0a4` | 18 |

The registry page can add any token and attach one contract/mint/denom/asset-id per supported chain. For example, a `LINK` token can use the Ethereum contract `0x514910771AF9Ca656af840dff83E8264EcF986CA` with 18 decimals.

## Price ids

Prices are resolved by CoinGecko id through DefiLlama, with CoinGecko as fallback:

| Symbol | CoinGecko id |
| --- | --- |
| ETH | `ethereum` |
| SOL | `solana` |
| BTC | `bitcoin` |
| CKB | `nervos-network` |
| ATOM | `cosmos` |
| STX | `blockstack` |
| SBTC | `sbtc-2` |
| USDT | `tether` |
| USDC | `usd-coin` |
| PAXG | `pax-gold` |
| XAUT | `tether-gold` |
| STETH | `staked-ether` |
| EARNETH | `lido-earn-eth` |

A custom token without a CoinGecko id is still tracked; its balance is saved with `price_usd = null` and the card total is marked `partial` if the balance is positive.

## Endpoint overrides

Set comma-separated overrides in `backend/.env`:

```dotenv
ASSETX_ETHEREUM_RPCS=https://your-eth-rpc.example,https://ethereum-rpc.publicnode.com
ASSETX_SOLANA_RPCS=https://your-solana-rpc.example
ASSETX_BITCOIN_APIS=https://blockstream.info/api,https://mempool.space/api
ASSETX_NERVOS_RPCS=https://mainnet.ckb.dev/rpc
ASSETX_COSMOS_APIS=https://cosmos-rest.publicnode.com
ASSETX_STACKS_APIS=https://api.hiro.so
```

Order matters: the first successful endpoint answers. Public endpoints are shared, rate limited, and offered without any SLA. For production or heavy usage, use a paid/private provider.

## Public endpoint caveats

- Rate limits change without notice.
- Some endpoints are geo-restricted.
- Indexed Solana methods may require an API token.
- Uniswap V3 discovery adds up to seven JSON-RPC round trips per Ethereum wallet. Wallets without positions stop after the first round trip.
- Uniswap V4 discovery adds one Blockscout request plus three to four RPC rounds. Blockscout indexes by block and can lag the chain head by a short time.
- Cosmos REST responses may paginate.
- Hiro Stacks API requests are rate limited per IP; a 429 triggers failover to the next host.
- The Hiro balances response includes every SIP-010 asset the wallet holds, so wallets with many spam tokens can return a large payload.
- Bitcoin APIs may return 429 under load; failover handles it.
- Prices are third-party data and can be delayed or missing.
