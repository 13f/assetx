"""Add the six public sample addresses used in the docs screenshots.

Start the API first, then run:
    python scripts/seed_demo.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
SAMPLES = [
    ("ethereum", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", ["Whale", "DeFi"]),
    ("solana", "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM", ["Solana", "Hot Wallet"]),
    ("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", ["Genesis", "Cold Storage"]),
    (
        "nervos",
        "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqdnnw7qkdnnclfkg59uzn8umtfd2kwxceqxwquc4",
        ["CKB"],
    ),
    ("cosmos", "cosmos1q4hjnwuat6zuxuplew5rvvw6yw3a4kwrm3e5ds", ["Cosmos Hub", "Staking"]),
    ("stacks", "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7", ["Stacks", "DeFi"]),
]


def request(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        content_type = response.headers.get("content-type", "")
        return response.status, json.loads(raw) if raw and "json" in content_type else None


def main() -> None:
    for chain, address, tags in SAMPLES:
        try:
            status, payload = request(
                "/api/addresses",
                "POST",
                {"chain": chain, "address": address, "tags": tags},
            )
            print(f"added {chain:9s} id={payload['id']}")
        except urllib.error.HTTPError as error:
            if error.code == 409:
                print(f"exists {chain:8s}")
            else:
                raise
    _, result = request("/api/addresses/refresh-all", "POST", {})
    print(f"queued {result['count']} refresh job(s)")


if __name__ == "__main__":
    main()
