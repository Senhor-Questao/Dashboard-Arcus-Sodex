"""
get_sodex_account_id.py
────────────────────────────────────────────────────────────────────────────
Descobre o SoDEX accountId de uma conta a partir apenas do endereço da
wallet (endereço EVM 0x...), sem precisar de API key nem de assinatura.

Endpoint usado (público, somente leitura):
    GET {BASE_URL}{PUBLIC_API}/accounts/{wallet}/state

A resposta é o objeto WsPerpsState da SoDEX, cujo campo "aid" é o
accountId da conta PRINCIPAL (master) associada àquela wallet.
Referência: https://sodex.com/documentation/trading-api/trading-api
            (seção "Get account ID")

Uso:
    python get_sodex_account_id.py 0xSuaWalletAqui
    # ou, sem argumento, o script pergunta interativamente:
    python get_sodex_account_id.py
"""

import sys
import asyncio
import aiohttp

BASE_URL   = "https://mainnet-gw.sodex.dev"   # igual ao bot original
PUBLIC_API = "/api/v1/perps"                  # igual ao bot original


def _pub_h() -> dict:
    """Mesmos headers públicos usados pelo bot original (_pub_h)."""
    return {"Accept": "application/json", "Origin": "https://sodex.com"}


async def get_account_id(wallet: str) -> dict:
    """
    Consulta /accounts/{wallet}/state e retorna o dict cru de dados
    (contém 'aid' = accountId, 'uid' = userId, além de saldos/posições).
    """
    wallet = wallet.strip()
    if not wallet.startswith("0x") or len(wallet) != 42:
        raise ValueError(f"Endereço de wallet inválido: {wallet!r}")

    url = f"{BASE_URL}{PUBLIC_API}/accounts/{wallet}/state"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_pub_h()) as r:
            r.raise_for_status()
            payload = await r.json(content_type=None)

    # Resposta no formato { "code": 0, "data": {...}, "timestamp": ... }
    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
    else:
        data = payload

    if not isinstance(data, dict) or "aid" not in data:
        raise RuntimeError(f"Resposta inesperada da SoDEX: {payload}")

    return data


async def main():
    if len(sys.argv) > 1:
        wallet = sys.argv[1]
    else:
        wallet = input("Endereço da wallet SoDEX (0x...): ").strip()

    try:
        data = await get_account_id(wallet)
    except Exception as e:
        print(f"❌ Erro ao consultar a wallet {wallet}: {e}")
        sys.exit(1)

    print()
    print(f"  🔑 Wallet     : {data.get('user', wallet)}")
    print(f"  🆔 accountId  : {data.get('aid')}")
    print(f"  👤 userId     : {data.get('uid')}")
    print()
    print("  (accountId acima é o da conta PRINCIPAL/master dessa wallet;")
    print("   subcontas exigem accountId específico, não descobrível só")
    print("   pela wallet.)")


if __name__ == "__main__":
    asyncio.run(main())
