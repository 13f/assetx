from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.chains.base import ChainAdapter
from app.chains.bitcoin import BitcoinAdapter
from app.chains.blockscout import DEFAULT_BLOCKSCOUT_APIS
from app.chains.cosmos import CosmosAdapter
from app.chains.ethereum import EthereumAdapter
from app.chains.nervos import NervosAdapter
from app.chains.solana import SolanaAdapter
from app.chains.stacks import StacksAdapter
from app.chains.uniswap import DEFAULT_NFT_COLLECTIONS, NftCollection, UNISWAP_V3_COLLECTION
from app.config import Settings
from app.utils.validation import EVM_ADDRESS_RE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainDefinition:
    id: str
    name: str
    native_symbol: str
    native_name: str
    native_decimals: int
    native_coingecko_id: str
    address_placeholder: str
    address_hint: str
    supports_tokens: bool
    token_standard: str | None
    explorer_url: str
    providers: tuple[str, ...]
    accent: str
    supports_nft_positions: bool = False


CHAIN_DEFINITIONS: dict[str, ChainDefinition] = {
    "ethereum": ChainDefinition(
        id="ethereum",
        name="Ethereum",
        native_symbol="ETH",
        native_name="Ether",
        native_decimals=18,
        native_coingecko_id="ethereum",
        address_placeholder="0x...",
        address_hint="EVM address: 0x followed by 40 hex characters",
        supports_tokens=True,
        token_standard="ERC-20",
        explorer_url="https://etherscan.io/address/{address}",
        providers=(
            "https://ethereum-rpc.publicnode.com",
            "https://eth.drpc.org",
            "https://1rpc.io/eth",
            "https://eth.llamarpc.com",
        ),
        accent="#627EEA",
        supports_nft_positions=True,
    ),
    "solana": ChainDefinition(
        id="solana",
        name="Solana",
        native_symbol="SOL",
        native_name="Solana",
        native_decimals=9,
        native_coingecko_id="solana",
        address_placeholder="Base58 public key",
        address_hint="Solana address: 32-byte base58 public key",
        supports_tokens=True,
        token_standard="SPL",
        explorer_url="https://solscan.io/account/{address}",
        providers=(
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
        ),
        accent="#14F195",
    ),
    "bitcoin": ChainDefinition(
        id="bitcoin",
        name="Bitcoin",
        native_symbol="BTC",
        native_name="Bitcoin",
        native_decimals=8,
        native_coingecko_id="bitcoin",
        address_placeholder="bc1... or 1... or 3...",
        address_hint="Bitcoin mainnet P2PKH, P2SH or SegWit address",
        supports_tokens=False,
        token_standard=None,
        explorer_url="https://mempool.space/address/{address}",
        providers=(
            "https://blockstream.info/api",
            "https://mempool.space/api",
        ),
        accent="#F7931A",
    ),
    "nervos": ChainDefinition(
        id="nervos",
        name="Nervos",
        native_symbol="CKB",
        native_name="Nervos Network",
        native_decimals=8,
        native_coingecko_id="nervos-network",
        address_placeholder="ckb1...",
        address_hint="Nervos CKB mainnet address (bech32 / bech32m)",
        supports_tokens=False,
        token_standard=None,
        explorer_url="https://explorer.nervos.org/address/{address}",
        providers=(
            "https://mainnet.ckb.dev/rpc",
            "https://mainnet.ckbapp.dev/rpc",
        ),
        accent="#3CC68A",
    ),
    "cosmos": ChainDefinition(
        id="cosmos",
        name="Cosmos",
        native_symbol="ATOM",
        native_name="Cosmos Hub",
        native_decimals=6,
        native_coingecko_id="cosmos",
        address_placeholder="cosmos1...",
        address_hint="Cosmos Hub account address (cosmos1...)",
        supports_tokens=True,
        token_standard="Cosmos SDK bank denom",
        explorer_url="https://www.mintscan.io/cosmos/address/{address}",
        providers=(
            "https://cosmos-rest.publicnode.com",
            "https://rest.cosmos.directory/cosmoshub",
            "https://cosmos-api.polkachu.com",
        ),
        accent="#6F7390",
    ),
    "stacks": ChainDefinition(
        id="stacks",
        name="Stacks",
        native_symbol="STX",
        native_name="Stacks",
        native_decimals=6,
        native_coingecko_id="blockstack",
        address_placeholder="SP... or SM...",
        address_hint="Stacks mainnet address (c32check, SP... or SM...)",
        supports_tokens=True,
        token_standard="SIP-010",
        explorer_url="https://explorer.hiro.so/address/{address}?chain=mainnet",
        providers=(
            "https://api.hiro.so",
            "https://api.mainnet.hiro.so",
        ),
        accent="#FC6432",
    ),
}

CHAIN_ORDER = list(CHAIN_DEFINITIONS)


def get_chain(chain: str) -> ChainDefinition | None:
    return CHAIN_DEFINITIONS.get(chain)


def _split_override(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def providers_for(chain: str, settings: Settings) -> list[str]:
    definition = CHAIN_DEFINITIONS[chain]
    override = {
        "ethereum": settings.ethereum_rpcs,
        "solana": settings.solana_rpcs,
        "bitcoin": settings.bitcoin_apis,
        "nervos": settings.nervos_rpcs,
        "cosmos": settings.cosmos_apis,
        "stacks": settings.stacks_apis,
    }[chain]
    return _split_override(override) or list(definition.providers)


def lp_collections_for(settings: Settings) -> tuple[NftCollection, ...]:
    """Position-manager contracts to scan for LP NFTs.

    Ethereum only. An empty override list keeps the canonical Uniswap V3
    position manager; disabling the feature returns no collections.
    """
    if not settings.ethereum_lp_positions_enabled:
        return ()
    overrides = _split_override(settings.ethereum_lp_position_managers)
    if not overrides:
        return DEFAULT_NFT_COLLECTIONS
    collections: list[NftCollection] = []
    for contract in overrides:
        if not EVM_ADDRESS_RE.fullmatch(contract):
            logger.warning("ignoring invalid LP position manager address: %s", contract)
            continue
        collections.append(
            NftCollection(
                protocol=UNISWAP_V3_COLLECTION.protocol,
                name=UNISWAP_V3_COLLECTION.name,
                contract_address=contract.lower(),
            )
        )
    if not collections:
        logger.warning(
            "no valid LP position managers configured; falling back to the built-in list"
        )
        return DEFAULT_NFT_COLLECTIONS
    return tuple(collections)


def blockscout_apis_for(settings: Settings) -> tuple[str, ...]:
    apis = _split_override(settings.ethereum_lp_blockscout_apis)
    return tuple(apis) or DEFAULT_BLOCKSCOUT_APIS


def chain_meta(chain: str, settings: Settings) -> dict[str, Any]:
    definition = CHAIN_DEFINITIONS[chain]
    return {
        "id": definition.id,
        "name": definition.name,
        "native_symbol": definition.native_symbol,
        "native_name": definition.native_name,
        "native_decimals": definition.native_decimals,
        "native_coingecko_id": definition.native_coingecko_id,
        "address_placeholder": definition.address_placeholder,
        "address_hint": definition.address_hint,
        "supports_tokens": definition.supports_tokens,
        "token_standard": definition.token_standard,
        "supports_nft_positions": definition.supports_nft_positions
        and (chain != "ethereum" or settings.ethereum_lp_positions_enabled),
        "explorer_url": definition.explorer_url,
        "provider_count": len(providers_for(chain, settings)),
        "accent": definition.accent,
    }


def build_adapters(settings: Settings, client: httpx.AsyncClient) -> dict[str, ChainAdapter]:
    classes = {
        "ethereum": EthereumAdapter,
        "solana": SolanaAdapter,
        "bitcoin": BitcoinAdapter,
        "nervos": NervosAdapter,
        "cosmos": CosmosAdapter,
        "stacks": StacksAdapter,
    }
    lp_collections = lp_collections_for(settings)
    lp_v4_enabled = (
        settings.ethereum_lp_positions_enabled and settings.ethereum_lp_v4_enabled
    )
    blockscout_apis = blockscout_apis_for(settings)
    adapters: dict[str, ChainAdapter] = {}
    for chain in CHAIN_ORDER:
        providers = providers_for(chain, settings)
        if chain == "ethereum":
            adapters[chain] = EthereumAdapter(
                providers,
                client,
                lp_collections=lp_collections,
                lp_max_positions=settings.ethereum_lp_max_positions,
                lp_v4_enabled=lp_v4_enabled,
                lp_v4_blockscout_apis=blockscout_apis,
            )
        else:
            adapters[chain] = classes[chain](providers, client)
    return adapters
