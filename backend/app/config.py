from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden with ASSETX_* env vars."""

    model_config = SettingsConfigDict(
        env_prefix="ASSETX_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AssetX"
    database_path: Path = BACKEND_DIR / "data" / "assetx.db"
    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"

    refresh_interval_seconds: float = 3.0
    request_timeout_seconds: float = 20.0
    price_cache_seconds: int = 15
    price_request_timeout_seconds: float = 15.0
    max_tags_per_address: int = 10

    # Development origins only. The Vite dev server proxies /api, so production
    # deployments usually do not need CORS at all.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Comma separated overrides. Leave blank to use the public defaults in
    # app/chains/registry.py.
    ethereum_rpcs: str = ""
    solana_rpcs: str = ""
    bitcoin_apis: str = ""
    nervos_rpcs: str = ""
    cosmos_apis: str = ""
    stacks_apis: str = ""

    # Uniswap V3 LP NFTs on Ethereum. Detection reads the canonical
    # NonfungiblePositionManager unless an explicit contract list is supplied.
    ethereum_lp_positions_enabled: bool = True
    ethereum_lp_position_managers: str = ""
    ethereum_lp_max_positions: int = 30

    # Uniswap V4 positions. The V4 position manager is not ERC-721 Enumerable,
    # so token ids come from a Blockscout NFT index before on-chain reads.
    ethereum_lp_v4_enabled: bool = True
    ethereum_lp_blockscout_apis: str = ""

    start_worker: bool = True
    log_level: str = "INFO"

    def model_post_init(self, __context: object) -> None:
        self.database_path = self.database_path.expanduser()
        self.frontend_dist = self.frontend_dist.expanduser()
        if not self.database_path.is_absolute():
            self.database_path = (PROJECT_DIR / self.database_path).resolve()
        if not self.frontend_dist.is_absolute():
            self.frontend_dist = (PROJECT_DIR / self.frontend_dist).resolve()

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]
