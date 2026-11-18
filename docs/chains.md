# Chains, tokens and public endpoints

AssetX tracks six chains. Each address belongs to exactly one chain, and each chain has its own native asset, address format, token model, and endpoint list.

## Overview

| Chain | Native | Decimals | Address format | Token support | Default endpoints |
| --- | --- | --- | --- | --- | --- |
| Ethereum | ETH | 18 | `0x` + 40 hex | ERC-20 | PublicNode, dRPC, 1RPC, LlamaRPC |
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

The database is seeded on first run. Later releases add new built-in tokens through versioned seed steps, so an existing database receives STX and sBTC on upgrade without re-adding tokens you deleted. Native tokens cannot be deleted or have their native network edited.

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
- Cosmos REST responses may paginate.
- Hiro Stacks API requests are rate limited per IP; a 429 triggers failover to the next host.
- The Hiro balances response includes every SIP-010 asset the wallet holds, so wallets with many spam tokens can return a large payload.
- Bitcoin APIs may return 429 under load; failover handles it.
- Prices are third-party data and can be delayed or missing.
