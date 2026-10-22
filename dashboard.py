"""
╔══════════════════════════════════════════╗
║   SoDEX TRADING BOT — Dashboard TUI     ║
║   Rich + Textual + Asyncio  │  btop-style ║
╚══════════════════════════════════════════╝

Requisitos:
    pip install rich textual aiohttp python-dotenv eth-account

Uso:
    python dashboard.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
#  BOOTSTRAP — verifica dependências, instala o que faltar e roda dentro do venv
#  (Linux/BigLinux-Manjaro e Windows 11). Roda ANTES dos imports de terceiros.
# ─────────────────────────────────────────────────────────────────────────────
import importlib as _importlib
import platform as _platform
import subprocess as _subprocess
import sys as _sys

# (nome no pip, módulo importado)
_REQUIRED_PACKAGES = [
    ("rich",          "rich"),
    ("textual",       "textual"),
    ("aiohttp",       "aiohttp"),
    ("python-dotenv", "dotenv"),
    ("eth-account",   "eth_account"),
    ("pycryptodome",  "Crypto"),        # keccak256
    ("cryptography",  "cryptography"),  # chave Ed25519 da Arcus (fallback X-API-Key)
]


def _bootstrap_describe_os() -> str:
    if os.name == "nt":
        try:
            win11 = int(_platform.version().split(".")[2]) >= 22000
        except Exception:  # noqa: BLE001
            win11 = False
        return "Windows 11" if win11 else f"Windows {_platform.release()}"
    try:
        with open("/etc/os-release", encoding="utf-8") as _f:
            for _line in _f:
                if _line.startswith("PRETTY_NAME="):
                    return _line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return _platform.system() or "Linux"


def _bootstrap_missing(py: str) -> list[str]:
    """Pacotes (nomes do pip) que o interpretador `py` ainda não consegue importar."""
    code = (
        "import importlib.util as u;"
        f"print(' '.join(p for p, m in {_REQUIRED_PACKAGES!r} if u.find_spec(m) is None))"
    )
    try:
        r = _subprocess.run([py, "-c", code], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.split()
    except OSError:
        pass
    return [p for p, _ in _REQUIRED_PACKAGES]


def _bootstrap_environment() -> None:
    # Já reiniciado pelo próprio bootstrap → segue direto (evita loop infinito)
    if os.environ.get("SODEX_BOOTSTRAPPED") == "1":
        return

    is_win   = os.name == "nt"
    script   = os.path.abspath(__file__)
    base_dir = os.path.dirname(script)
    venv_dir = next(
        (p for p in (os.path.join(base_dir, "venv"), os.path.join(base_dir, ".venv"))
         if os.path.isdir(p)),
        os.path.join(base_dir, "venv"),
    )
    venv_py = os.path.join(venv_dir, "Scripts" if is_win else "bin",
                           "python.exe" if is_win else "python")
    in_venv = os.path.realpath(_sys.prefix) == os.path.realpath(venv_dir)
    py      = _sys.executable if in_venv else venv_py
    os_name = _bootstrap_describe_os()

    # 1) venv inexistente → cria na pasta do dashboard
    if not in_venv and not os.path.isfile(venv_py):
        print(f"⚙  [{os_name}] Ambiente virtual não encontrado em: {venv_dir}")
        print(f"   $ {_sys.executable} -m venv {venv_dir}")
        if _subprocess.call([_sys.executable, "-m", "venv", venv_dir]) != 0 \
                or not os.path.isfile(venv_py):
            print("❌ Não foi possível criar o venv.")
            if is_win:
                print("   Reinstale o Python em python.org marcando 'pip' e 'py launcher',")
                print("   ou use:  winget install Python.Python.3.12")
            else:
                print("   Instale o Python completo no sistema:  sudo pacman -S python")
            _sys.exit(1)

    # 2) confere pacotes e instala o que faltar (dentro do venv)
    missing = _bootstrap_missing(py)
    if missing:
        print(f"⚙  [{os_name}] Pacotes necessários ainda não instalados:")
        for _pkg in missing:
            print(f"     • {_pkg}")
        cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", *missing]
        print(f"   $ {' '.join(cmd)}")
        if _subprocess.call(cmd) != 0:
            print("❌ Falha ao instalar os pacotes. Verifique sua conexão e tente novamente.")
            _sys.exit(1)
        still = _bootstrap_missing(py)
        if still:
            print(f"❌ Ainda faltam pacotes após a instalação: {', '.join(still)}")
            _sys.exit(1)
        print("✓ Dependências instaladas.")

    # 3) fora do venv → reinicia o dashboard dentro dele
    if not in_venv:
        os.environ["SODEX_BOOTSTRAPPED"] = "1"
        argv = [venv_py, script, *_sys.argv[1:]]
        if is_win:  # os.execv no Windows não preserva bem o terminal
            try:
                _sys.exit(_subprocess.call(argv))
            except KeyboardInterrupt:
                _sys.exit(130)
        os.execv(venv_py, argv)
    else:
        _importlib.invalidate_caches()


if __name__ == "__main__":
    _bootstrap_environment()


import aiohttp
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Footer, Header
from textual.reactive import reactive
from textual import work
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.console import Console, Group as rich_group
from rich.style import Style
from rich import box as rbox

# ─────────────────────────────────────────────────────────────────────────────
#  VARIÁVEIS DE AMBIENTE
# ─────────────────────────────────────────────────────────────────────────────
load_dotenv()

SODEX_PUBLIC_KEY     = os.environ.get("SODEX_PUBLIC_KEY", "")       # nome da API key (ex: "API2")
SODEX_PRIVATE_KEY    = os.environ.get("SODEX_PRIVATE_KEY", "")      # chave privada EVM 0x... (66 chars)
SODEX_ACCOUNT_ID     = int(os.environ.get("SODEX_ACCOUNT_ID", "0")) # ID numérico da sub-conta
SODEX_WALLET_ADDRESS = os.environ.get("SODEX_WALLET_ADDRESS", "")   # endereço EVM da wallet mestre

# ── Conta 2 — segunda API/wallet, totalmente separada ──────────────────────
SODEX_PUBLIC_KEY_CONTA_2     = os.environ.get("SODEX_PUBLIC_KEY_CONTA_2", "")
SODEX_PRIVATE_KEY_CONTA_2    = os.environ.get("SODEX_PRIVATE_KEY_CONTA_2", "")
SODEX_ACCOUNT_ID_CONTA_2     = int(os.environ.get("SODEX_ACCOUNT_ID_CONTA_2", "0") or "0")
SODEX_WALLET_ADDRESS_CONTA_2 = os.environ.get("SODEX_WALLET_ADDRESS_CONTA_2", "")

# ── Conta 3 — Arcus (somente leitura, API REST pública) ─────────────────────
# Mesmas variáveis usadas pelo dashboard1.py / check_setup.py. A chave de
# assinatura é opcional (só serve de fallback X-API-Key em caso de 401/403).
def _arcus_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


ARCUS_ENV            = _arcus_env("ARCUS_ENV").lower()                 # testnet | mainnet
ARCUS_REST_URL       = _arcus_env("ARCUS_REST_URL").rstrip("/")        # ex.: https://api.arcus.xyz
ARCUS_WALLET_ADDRESS = _arcus_env("ARCUS_WALLET_ADDRESS")              # carteira master (0x + 40 hex)
ARCUS_ACCOUNT_INDEX  = 0                                               # subconta (0-9), padrão 0

ARCUS_CONFIG_ERRORS: list[str] = []
if not ARCUS_REST_URL:
    ARCUS_CONFIG_ERRORS.append("ARCUS_REST_URL ausente ou vazia")
elif not ARCUS_REST_URL.startswith(("https://", "http://")):
    ARCUS_CONFIG_ERRORS.append("ARCUS_REST_URL deve começar com https://")
if not ARCUS_WALLET_ADDRESS:
    ARCUS_CONFIG_ERRORS.append("ARCUS_WALLET_ADDRESS ausente ou vazia")
elif not re.fullmatch(r"0x[0-9a-fA-F]{40}", ARCUS_WALLET_ADDRESS):
    ARCUS_CONFIG_ERRORS.append("ARCUS_WALLET_ADDRESS deve ser 0x + 40 caracteres hex")
try:
    ARCUS_ACCOUNT_INDEX = int(_arcus_env("ARCUS_ACCOUNT_INDEX", "0") or "0")
    if not 0 <= ARCUS_ACCOUNT_INDEX <= 9:
        raise ValueError
except ValueError:
    ARCUS_CONFIG_ERRORS.append("ARCUS_ACCOUNT_INDEX deve ser inteiro entre 0 e 9")


def _derive_api_key_pub() -> str:
    """Chave pública Ed25519 derivada de ARCUS_API_SIGNING_KEY (a privada NUNCA é usada
    para assinar nem impressa aqui). Só serve de fallback: se a API responder 401/403 numa
    leitura, tentamos de novo com o header X-API-Key. Retorna "" se não houver chave válida
    ou se o pacote 'cryptography' não estiver instalado."""
    key_hex = _arcus_env("ARCUS_API_SIGNING_KEY").removeprefix("0x")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key_hex):
        return ""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex))
        return priv.public_key().public_bytes_raw().hex()
    except Exception:  # noqa: BLE001
        return ""


ARCUS_API_KEY_PUB = _derive_api_key_pub()

# ── Registro das contas disponíveis no dashboard ────────────────────────────
# Tecla [1] exibe a Conta 1, tecla [2] exibe a Conta 2, tecla [3] exibe a Arcus
# — cada uma com seu próprio par de credenciais/wallet, lidas do .env.
ACCOUNTS: dict[int, dict] = {
    1: {
        "label":      "Conta 1",
        "public_key": SODEX_PUBLIC_KEY,
        "private_key": SODEX_PRIVATE_KEY,
        "account_id": SODEX_ACCOUNT_ID,
        "wallet":     SODEX_WALLET_ADDRESS,
    },
    2: {
        "label":      "Conta 2",
        "public_key": SODEX_PUBLIC_KEY_CONTA_2,
        "private_key": SODEX_PRIVATE_KEY_CONTA_2,
        "account_id": SODEX_ACCOUNT_ID_CONTA_2,
        "wallet":     SODEX_WALLET_ADDRESS_CONTA_2,
    },
    3: {
        "label":      "Arcus",
        "venue":      "arcus",          # usa as funções *_arcus (API REST da Arcus)
        "public_key": "",
        "private_key": "",
        "account_id": ARCUS_ACCOUNT_INDEX,
        "wallet":     ARCUS_WALLET_ADDRESS,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  PALETA  (estilo btop / dark terminal)
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg":          "#1a1b26",
    "panel_bg":    "#1e2030",
    "border":      "#3b4261",
    "title":       "#7dcfff",
    "header":      "#565f89",
    "text":        "#c0caf5",
    "dim":         "#565f89",
    "green":       "#9ece6a",
    "red":         "#f7768e",
    "yellow":      "#e0af68",
    "cyan":        "#7dcfff",
    "magenta":     "#bb9af7",
    "orange":      "#ff9e64",
    "white":       "#c0caf5",
    "long":        "#9ece6a",
    "short":       "#f7768e",
    "profit":      "#9ece6a",
    "loss":        "#f7768e",
    "neutral":     "#7dcfff",
    "bot_icon":    "#bb9af7",
    "user_icon":   "#7dcfff",
    "tp_col":      "#9ece6a",
    "sl_col":      "#f7768e",
    "trl_col":     "#e0af68",
    "pending":     "#e0af68",
    "signal":      "#7dcfff",
    "row_shade":   "#232541",
}

REFRESH_SECS = 2  # Atualização a cada 2s

# ─────────────────────────────────────────────────────────────────────────────
#  LEITURA DO ESTADO DO BOT — trailing_count por símbolo
#  O trading_bot.py persiste o estado das posições em bot_state.json
#  na mesma pasta. O campo "trailing_count" de cada posição indica
#  quantos steps de trailing foram aplicados pelo bot.
# ─────────────────────────────────────────────────────────────────────────────

BOT_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")


def _read_bot_trailing_counts() -> dict[str, int]:
    """
    Lê o arquivo bot_state.json gerado pelo trading_bot.py e retorna
    um dicionário { symbol: trailing_count } para cada posição gerenciada.
    Retorna {} se o arquivo não existir ou estiver malformado.
    """
    try:
        if not os.path.exists(BOT_STATE_FILE):
            return {}
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # Suporta { "positions": { "BTC-USD": { "trailing_count": 3, ... } } }
        # e também lista de positions
        positions_data = state.get("positions", state)
        counts: dict[str, int] = {}
        if isinstance(positions_data, dict):
            for sym, pos in positions_data.items():
                if isinstance(pos, dict):
                    counts[sym] = int(pos.get("trailing_count", 0))
        elif isinstance(positions_data, list):
            for pos in positions_data:
                if isinstance(pos, dict):
                    sym = pos.get("symbol", pos.get("s", ""))
                    if sym:
                        counts[sym] = int(pos.get("trailing_count", 0))
        return counts
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
#  SODEX API — Endpoints reais (mainnet)
#  Documentação: https://sodex.com/documentation/trading-api/rest-v1
# ─────────────────────────────────────────────────────────────────────────────

PERPS_ENDPOINT = "https://mainnet-gw.sodex.dev/api/v1/perps"
SPOT_ENDPOINT  = "https://mainnet-gw.sodex.dev/api/v1/spot"

# Chain ID mainnet SoDEX (ValueChain)
CHAIN_ID_MAINNET = 286623

# ── Precisão de preço por símbolo, definida pela SoDEX ──────────────────────
# Populado por fetch_market_precision() a partir de GET /perps/markets/symbols e
# consumido por _fmt_price() para exibir cada ativo com o número exato de
# casas decimais configurado pela corretora (em vez de uma heurística fixa).
# { "BTC-USD": 1, "DOGE-USD": 5, ... }
MARKET_PRECISION: dict[str, int] = {}

# Precisão de preço da ARCUS (separada da SoDEX: o mesmo símbolo, ex. "BTC-USD",
# pode ter casas decimais diferentes em cada corretora). Populado via GET /v1/markets.
ARCUS_MARKET_PRECISION: dict[str, int] = {}
# Corretora cuja conta está sendo exibida ("sodex" | "arcus") — escolhe a tabela
# de precisão usada por _fmt_price().
_ACTIVE_VENUE = "sodex"

# ─────────────────────────────────────────────────────────────────────────────
#  AUTENTICAÇÃO EIP-712
#  A SoDEX usa assinatura EIP-712 (typed structured data), NÃO HMAC.
#  - X-API-Key  → nome da chave (string, ex: "API2")
#  - X-API-Sign → assinatura EIP-712 com prefixo 0x01
#  - X-API-Nonce → timestamp em ms (único e crescente)
#
#  Endpoints de leitura (GET) são PÚBLICOS — não precisam de autenticação.
#  Apenas endpoints de escrita (POST/DELETE) precisam de assinatura.
# ─────────────────────────────────────────────────────────────────────────────

def _eip712_sign_payload(payload_json: str, nonce: int, domain_name: str = "futures") -> str:
    """
    Assina um payload de ação de trading usando EIP-712 (padrão SoDEX).

    Parâmetros:
        payload_json: JSON compacto da ação, ex: '{"type":"newOrder","params":{...}}'
        nonce: timestamp em ms (deve ser único e crescente)
        domain_name: "futures" para perps, "spot" para spot

    Retorna:
        Assinatura hex com prefixo 0x01 (typed signature no formato SoDEX)
    """
    import hashlib

    # payloadHash = keccak256(compact JSON)
    payload_bytes = payload_json.encode("utf-8")
    payload_hash = "0x" + hashlib.new("sha3_256", payload_bytes).hexdigest()
    # Nota: SoDEX usa keccak256 (sha3), não SHA-256 padrão
    # eth_account já faz o keccak256 internamente no encode_typed_data

    from eth_account._utils.structured_data.hashing import hash_message
    from eth_account.messages import encode_typed_data

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name",              "type": "string"},
                {"name": "version",           "type": "string"},
                {"name": "chainId",           "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "ExchangeAction": [
                {"name": "payloadHash", "type": "bytes32"},
                {"name": "nonce",       "type": "uint64"},
            ],
        },
        "domain": {
            "name":              domain_name,
            "version":           "1",
            "chainId":           CHAIN_ID_MAINNET,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "primaryType": "ExchangeAction",
        "message": {
            "payloadHash": _keccak256_hex(payload_json.encode()),
            "nonce":       nonce,
        },
    }

    signable = encode_typed_data(full_message=typed_data)
    signed   = Account.sign_message(signable, private_key=SODEX_PRIVATE_KEY)

    # Prepend byte 0x01 para typed signature (padrão SoDEX)
    sig_bytes = signed.signature
    typed_sig = "0x01" + sig_bytes.hex()[2:]  # remove "0x" e adiciona prefixo correto
    return typed_sig


def _keccak256_hex(data: bytes) -> str:
    """Retorna keccak256 de `data` como string hex 0x..."""
    from eth_account._utils.legacy_transactions import encode_transaction
    from Crypto.Hash import keccak as _keccak
    k = _keccak.new(digest_bits=256)
    k.update(data)
    return "0x" + k.hexdigest()


def _keccak256_hex_safe(data: bytes) -> str:
    """Keccak256 usando web3 ou pycryptodome, com fallback."""
    try:
        from Crypto.Hash import keccak as _keccak
        k = _keccak.new(digest_bits=256)
        k.update(data)
        return "0x" + k.hexdigest()
    except ImportError:
        pass
    try:
        from eth_hash.auto import keccak
        return "0x" + keccak(data).hex()
    except ImportError:
        raise RuntimeError(
            "Instale pycryptodome ou eth-hash para hashing keccak256:\n"
            "  pip install pycryptodome\n"
            "ou\n"
            "  pip install eth-hash[pycryptodome]"
        )


def _build_signed_headers(payload_json: str, domain_name: str = "futures") -> dict:
    """
    Monta os headers autenticados para endpoints de escrita da SoDEX.
    Endpoints de leitura (GET account data) são públicos — não precisam destes headers.
    """
    nonce = int(time.time() * 1000)  # timestamp em ms
    sig   = _eip712_sign_payload(payload_json, nonce, domain_name)
    return {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    SODEX_PUBLIC_KEY,   # nome da chave (string), ex: "API2"
        "X-API-Sign":   sig,
        "X-API-Nonce":  str(nonce),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CLIENTE HTTP — GET público (sem autenticação para leitura)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_public(
    session: aiohttp.ClientSession,
    url: str,
    params: dict | None = None,
) -> Any:
    """GET público na API SoDEX (sem autenticação — endpoints de leitura são abertos)."""
    headers = {"Accept": "application/json"}
    async with session.get(
        url,
        headers=headers,
        params=params,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _post_signed(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    domain_name: str = "futures",
) -> Any:
    """POST autenticado (EIP-712) na API SoDEX — para operações de escrita."""
    body    = json.dumps(payload, separators=(",", ":"))
    headers = _build_signed_headers(body, domain_name)
    async with session.post(
        url,
        headers=headers,
        data=body,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


# ─────────────────────────────────────────────────────────────────────────────
#  PARSERS — adaptam o JSON da SoDEX ao formato interno do dashboard
#  Baseados no schema real: https://sodex.com/documentation/trading-api/rest-v1/schema
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Converte DecimalString ou número para float com segurança."""
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _parse_state(raw: Any, mark_prices: dict[str, float] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Extrai posições abertas e ordens pendentes do endpoint /state.

    Schema real da SoDEX (campos abreviados):
    ── data ──────────────────────────────────────────────────────────────────
      "P"  → lista de posições abertas
      "O"  → lista de ordens (limit + stop)
      "B"  → balances

    ── Posição (item de "P") ─────────────────────────────────────────────────
      "s"   → symbol       ex: "BTC-USD"
      "sz"  → size         negativo = SHORT, positivo = LONG
      "ep"  → entry price  (avgEntryPrice)
      "cp"  → current mark price
      "ur"  → unrealized PnL (já calculado pela exchange)
      "cr"  → realized PnL
      "iw"  → initial margin (isolada)
      "i"   → position ID  (usado para vincular ordens)
      "l"   → alavancagem

    ── Ordem de stop (item de "O" com campo "R": true) ──────────────────────
      "s"   → symbol
      "sp"  → stop price
      "st"  → "TAKE_PROFIT" ou "STOP_LOSS"
      "pid" → position ID que esta ordem protege
      "R"   → true = ordem de redução (stop/tp/sl)
      "p"   → limit price (ordens limit normais)
      "q"   → quantity
      "S"   → side: "BUY" | "SELL"
    """
    if mark_prices is None:
        mark_prices = {}

    data = raw.get("data", raw) if isinstance(raw, dict) else {}

    raw_positions = data.get("P", []) or []
    raw_orders    = data.get("O", []) or []

    # ── Indexa ordens STOP/TP ──────────────────────────────────────────────
    # Campos confirmados pelo diagnóstico real da API SoDEX:
    #   stop["poid"] → aponta para limit["i"]  (ordem limit pai)
    #   stop["pid"]  → aponta para pos["i"]    (posição aberta)
    #   stop["sp"]   → preço do stop
    tp_by_pid:    dict[int, float] = {}   # pos["i"]   → TP
    sl_by_pid:    dict[int, float] = {}   # pos["i"]   → SL
    tp_by_poid:   dict[int, float] = {}   # limit["i"] → TP
    sl_by_poid:   dict[int, float] = {}   # limit["i"] → SL
    tp_by_symbol: dict[str, float] = {}   # fallback
    sl_by_symbol: dict[str, float] = {}   # fallback

    # IDs ("i") das ordens que são efetivamente TP/SL vinculados a uma posição
    # ou a uma ordem limit pai. Usado para não confundir uma ordem limit
    # reduce-only comum (R=true, mas sem classificação TP/SL) com um stop —
    # essas devem continuar aparecendo em ORDENS PENDENTES.
    stop_order_ids: set[int] = set()

    for order in raw_orders:
        if not order.get("R", False):
            continue
        stop_type  = str(order.get("st") or "")
        stop_price = _safe_float(order.get("sp"))
        sym        = str(order.get("s", ""))
        pid        = order.get("pid")    # vínculo com posição aberta
        poid       = order.get("poid")   # vínculo com ordem limit pai

        is_tp = "TAKE_PROFIT" in stop_type.upper()
        is_sl = "STOP_LOSS"   in stop_type.upper()

        if is_tp:
            if pid  is not None: tp_by_pid[int(pid)]   = stop_price
            if poid is not None: tp_by_poid[int(poid)] = stop_price
            tp_by_symbol[sym] = stop_price
        elif is_sl:
            if pid  is not None: sl_by_pid[int(pid)]   = stop_price
            if poid is not None: sl_by_poid[int(poid)] = stop_price
            sl_by_symbol[sym] = stop_price

        if is_tp or is_sl:
            order_id = order.get("i")
            if order_id is not None:
                stop_order_ids.add(int(order_id))

    # ── Parseia posições ────────────────────────────────────────────────────
    positions = []
    for item in raw_positions:
        symbol   = str(item.get("s", "???"))
        par      = symbol.split("-")[0].upper()
        pos_id   = item.get("i")

        size_raw = _safe_float(item.get("sz"))
        if size_raw == 0.0:
            continue  # posição zerada — ignora

        direction = "LONG" if size_raw > 0 else "SHORT"

        entry        = _safe_float(item.get("ep"))
        mark         = mark_prices.get(symbol) or _safe_float(item.get("cp")) or entry
        upnl         = _safe_float(item.get("ur"))   # uPnL não realizado da posição
        realized_pnl = _safe_float(item.get("cr"))   # PnL realizado acumulado (não exibido no painel)
        leverage     = int(item.get("l", 1) or 1)
        liq_price    = _safe_float(item.get("lp"))

        # Margem da posição: "iw" só vem preenchido no modo ISOLATED
        # ("m": "ISOLATED"). No modo CROSS ("m": "CROSS") a SoDEX não
        # preenche "iw" (fica ausente/0) — nesse caso a margem usada é
        # calculada como nocional ÷ alavancagem, usando "co" (valor
        # nocional da posição) e "l" (alavancagem), com fallback extra
        # para size × entry_price quando "co" também estiver ausente.
        # Confirmado via diagnóstico real: contas em CROSS nunca trazem
        # "iw" no payload de posições.
        margin = _safe_float(item.get("iw"))
        if margin == 0.0:
            notional = _safe_float(item.get("co"))
            if notional == 0.0:
                notional = abs(size_raw) * entry
            margin = notional / leverage if leverage else 0.0

        # Vínculo confirmado: pos["i"] → stop["pid"]
        if pos_id is not None:
            pid_int = int(pos_id)
            tp = tp_by_pid.get(pid_int) or tp_by_symbol.get(symbol)
            sl = sl_by_pid.get(pid_int) or sl_by_symbol.get(symbol)
        else:
            tp = tp_by_symbol.get(symbol)
            sl = sl_by_symbol.get(symbol)

        positions.append({
            "par":           par,
            "symbol":        symbol,
            "pos_id":        pos_id,
            "dir":           direction,
            "pnl":           round(upnl, 4),        # uPnL apenas — igual ao exibido na SoDEX
            "upnl":          round(upnl, 4),
            "realizedPnl":   round(realized_pnl, 4),
            # Mantém mais casas que o necessário aqui de propósito — quem
            # decide as casas decimais finais exibidas é _fmt_price(),
            # usando a precisão oficial do símbolo (MARKET_PRECISION).
            # Arredondar cedo demais (ex.: 4 casas fixas) cortaria ativos
            # cuja precisão SoDEX seja maior que isso.
            "preco":         round(mark, 8),
            "entry":         round(entry, 8),
            "size":          size_raw,
            "leverage":      leverage,
            "liq_price":     round(liq_price, 4),
            "tp":            tp,
            "sl":            sl,
            "trl":           0,
            "owner":         "bot",
            "initialMargin": margin,
        })

    # ── Parseia ordens limit pendentes (não-stop) ───────────────────────────
    orders = []
    for item in raw_orders:
        item_id = item.get("i")
        if item.get("R", False) and (item_id is None or int(item_id) in stop_order_ids):
            continue  # exclui apenas TP/SL já vinculados a posição/ordem — demais ordens (inclusive limit reduce-only) seguem como pendentes
        symbol  = str(item.get("s", "???"))
        par     = symbol.split("-")[0].upper()
        entrada = _safe_float(item.get("p"))
        size    = _safe_float(item.get("q"))
        side    = str(item.get("S", ""))
        # Vínculo confirmado: limit["i"] → stop["poid"]
        order_id = item.get("i")
        tp = None
        sl = None
        if order_id is not None:
            tp = tp_by_poid.get(int(order_id))
            sl = sl_by_poid.get(int(order_id))
        # Sem fallback por símbolo aqui: um TP/SL só deve ser exibido nesta
        # ordem limit se estiver de fato vinculado a ela (via "poid"). Caso
        # contrário, o campo permanece vazio ("----") no painel.

        mark     = mark_prices.get(symbol, 0.0)
        notional = abs(size) * entrada if entrada else 0.0
        orders.append({
            "par":     par,
            "symbol":  symbol,
            "side":    side,
            "entrada": entrada,
            "mark":    mark,
            "tp":      tp or 0.0,
            "sl":      sl or 0.0,
            "size":    round(notional, 2),
        })

    return positions, orders


def _parse_account(raw_state: Any, positions: list[dict]) -> dict:
    """
    Extrai saldo da conta do payload /state com cobertura ampla de schemas.

    Campos tentados em ordem de prioridade:
      Raiz do data:  "av", "am", "im"  (campos curtos SoDEX)
      Lista "B":     item com "a" == "vUSDC"/"USDC"
                     "wb" (wallet balance), "aw" (available), "iw" (initial margin)
      Nomes longos:  walletBalance, availableBalance, positionMargin, etc.

    Margem em uso — cobre CROSS e ISOLATED:
      Se "im" (raiz) e "iw" (balance) vierem zerados, cai para a soma de
      "initialMargin" de cada posição aberta (`positions`). Esse campo já
      vem calculado corretamente por `_parse_state` tanto para posições
      ISOLATED (via "iw" da própria posição) quanto para posições CROSS
      (via nocional "co" ÷ alavancagem "l", já que a SoDEX não preenche
      "iw" por posição nesse modo).
    """
    # Desempacota envelope { "data": {...} } se presente
    if isinstance(raw_state, dict):
        data = raw_state.get("data", raw_state)
        if not isinstance(data, dict):
            data = raw_state
    else:
        data = {}

    # ── 1. Campos curtos na raiz do data ──────────────────────────────────────
    av_root = _safe_float(data.get("av"))   # account value / wallet balance total
    am_root = _safe_float(data.get("am"))   # available margin
    im_root = _safe_float(data.get("im"))   # initial margin em uso

    # ── 2. Lista "B" de balances ──────────────────────────────────────────────
    balances_list = data.get("B") or data.get("balances") or []
    if not isinstance(balances_list, list):
        balances_list = []

    # Prefere vUSDC, depois USDC, senão primeiro item
    bal: dict = {}
    for b in balances_list:
        if isinstance(b, dict) and str(b.get("a", "")).upper() in ("VUSDC", "USDC"):
            bal = b
            break
    if not bal and balances_list and isinstance(balances_list[0], dict):
        bal = balances_list[0]

    # wb = wallet balance; aw = available; iw = initial/margin em uso
    wb = _safe_float(bal.get("wb") or bal.get("walletBalance")     or bal.get("balance"))
    aw = _safe_float(bal.get("aw") or bal.get("availableBalance")  or bal.get("freeCollateral"))
    iw = _safe_float(bal.get("iw") or bal.get("positionMargin")    or bal.get("initialMarginUsed"))

    # uPnL = soma de upnl das posições abertas
    upnl = sum(p.get("upnl", 0.0) for p in positions)

    # ── 3. Monta valores finais com fallback em cascata ───────────────────────
    wallet_balance = wb or av_root
    available      = aw or am_root
    margin         = iw or im_root

    # Fallback calculado a partir das posições quando campos ausentes
    if margin == 0.0:
        margin = sum(p.get("initialMargin", 0.0) for p in positions)
    if available == 0.0 and wallet_balance > 0:
        available = max(wallet_balance - margin, 0.0)

    # Saldo Total = equity = wallet balance + uPnL (igual ao exibido na SoDEX)
    total = wallet_balance + upnl

    return {
        "total":     round(total,          2),
        "available": round(available,      2),
        "margin":    round(margin,         2),
        "upnl":      round(upnl,           2),
    }


def _parse_history(raw: Any) -> list[dict]:
    """
    Converte histórico de posições fechadas dos últimos 7 dias.
    Endpoint: GET /perps/accounts/{wallet}/positions/history

    Schema real SoDEX (campos abreviados, igual ao /state):
      "s"   -> symbol          ex: "BTC-USD"
      "sz"  -> size final      negativo = SHORT, positivo = LONG
      "cr"  -> realized PnL
      "ep"  -> entry price
      "ut"  -> updatedAt (ms) timestamp de fechamento
      "ct"  -> createdAt (ms)

    Fallback para schemas alternativos com nomes longos.
    """
    results = []
    data    = raw.get("data", []) if isinstance(raw, dict) else []

    if isinstance(data, dict):
        items = (
            data.get("positions", [])
            or data.get("list",      [])
            or data.get("records",   [])
            or []
        )
    elif isinstance(data, list):
        items = data
    else:
        items = []

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    for item in items:
        if not isinstance(item, dict):
            continue

        # Timestamp de fechamento
        ts_raw = (
            item.get("ut")
            or item.get("ct")
            or item.get("closedAt")
            or item.get("closeTime")
            or item.get("updatedAt")
        )
        if ts_raw:
            try:
                ts = datetime.fromtimestamp(int(ts_raw) / 1000, tz=timezone.utc)
                if ts < cutoff:
                    continue
            except Exception:
                pass

        symbol = str(item.get("s") or item.get("symbol") or "???")
        par    = symbol.split("-")[0].upper()

        # Direção: campo "sz" (size) negativo=SHORT / positivo=LONG
        sz = item.get("sz")
        if sz is not None:
            direction = "LONG" if _safe_float(sz) > 0 else "SHORT"
        else:
            side = str(
                item.get("side")
                or item.get("positionSide")
                or item.get("S")
                or "BUY"
            )
            direction = "LONG" if side.upper() in ("BUY", "LONG", "1") else "SHORT"

        # PnL realizado: "cr" no schema abreviado
        pnl = _safe_float(
            item.get("cr")
            or item.get("realizedPnl")
            or item.get("realizedPnL")
            or item.get("pnl")
            or 0
        )

        # Preço de fechamento: "cp" no schema abreviado (mesmo campo usado
        # como "current price"/mark em posições abertas; em histórico
        # representa o preço em que a posição foi efetivamente encerrada).
        # Fallbacks cobrem nomes alternativos usados por outros schemas.
        close_price = _safe_float(
            item.get("cp")
            or item.get("closePrice")
            or item.get("exitPrice")
            or item.get("avgClosePrice")
            or item.get("px")
            or 0
        )

        results.append({
            "par":         par,
            "dir":         direction,
            "pnl":         round(pnl, 4),
            "close_price": round(close_price, 4) if close_price else None,
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
#  FETCH FUNCTIONS — chamadas reais à API SoDEX (endpoints corretos)
#  Documentação: https://sodex.com/documentation/trading-api/rest-v1/sodex-rest-perps-api
#
#  IMPORTANTE: endpoints GET de conta são PÚBLICOS (sem auth).
#  Apenas use o endereço da wallet na URL; o accountID vai como query param.
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_mark_prices(session: aiohttp.ClientSession) -> dict[str, float]:
    """
    Busca mark prices de todos os mercados.
    GET /perps/markets/mark-prices
    Retorna dict { "BTC-USD": 65000.5, ... }
    """
    url = f"{PERPS_ENDPOINT}/markets/mark-prices"
    try:
        raw  = await _get_public(session, url)
        data = raw.get("data", raw) if isinstance(raw, dict) else []
        # Suporta lista [ {"symbol": "BTC-USD", "markPrice": "65000.5"}, ... ]
        # ou dict { "BTC-USD": "65000.5", ... }
        if isinstance(data, list):
            return {
                str(item.get("symbol", "")): float(item.get("markPrice", "0") or 0)
                for item in data
                if item.get("symbol")
            }
        if isinstance(data, dict):
            return {k: float(v or 0) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _decimals_from_tick(tick_value: Any) -> int | None:
    """Deriva o número de casas decimais a partir de um tick size
    (ex.: tickSize "0.001" → 3 casas). Retorna None se não for possível."""
    try:
        from decimal import Decimal
        exponent = Decimal(str(tick_value)).normalize().as_tuple().exponent
        return max(-int(exponent), 0) if isinstance(exponent, int) else 0
    except Exception:
        return None


async def fetch_market_precision(session: aiohttp.ClientSession) -> dict[str, int]:
    """
    Busca a lista de mercados da SoDEX e extrai a precisão de preço
    (casas decimais) definida pela corretora para cada símbolo.
    GET /perps/markets/symbols  → Array<PerpsSymbol>
    (endpoint oficial: https://sodex.com/documentation/trading-api/rest-v1/sodex-rest-perps-api)

    O schema exato pode variar; tenta, em ordem:
      1. campo de precisão já em número de casas decimais
         ("pricePrecision", "price_precision", "priceDecimals", "pp", "priceScale")
      2. tick size, do qual as casas decimais são derivadas
         ("tickSize", "ts", "minPriceIncrement", "priceTick", "tick_size")

    Retorna { "BTC-USD": 1, "DOGE-USD": 5, ... }. Retorna {} em caso de
    falha — nesse caso _fmt_price() cai para a heurística de fallback.
    """
    url = f"{PERPS_ENDPOINT}/markets/symbols"
    precisions: dict[str, int] = {}
    try:
        raw   = await _get_public(session, url)
        data  = raw.get("data", raw) if isinstance(raw, dict) else raw
        items = data if isinstance(data, list) else (
            data.get("markets") or data.get("list") or [] if isinstance(data, dict) else []
        )
        if not isinstance(items, list):
            return {}

        for item in items:
            if not isinstance(item, dict):
                continue
            # O PerpsSymbol real de /markets/symbols não tem campo "symbol"
            # nem "s" — o identificador do par (ex.: "BTC-USD") vem em "name".
            symbol = str(item.get("symbol") or item.get("s") or item.get("name") or "")
            if not symbol:
                continue

            decimals: int | None = None
            for key in ("pricePrecision", "price_precision", "priceDecimals",
                        "pp", "priceScale"):
                if item.get(key) is not None:
                    try:
                        decimals = int(item[key])
                        break
                    except (TypeError, ValueError):
                        pass

            if decimals is None:
                for key in ("tickSize", "ts", "minPriceIncrement",
                            "priceTick", "tick_size"):
                    if item.get(key) is not None:
                        decimals = _decimals_from_tick(item[key])
                        if decimals is not None:
                            break

            if decimals is not None and decimals >= 0:
                precisions[symbol] = decimals
    except Exception:
        return {}
    return precisions


async def fetch_all(wallet_address: str = SODEX_WALLET_ADDRESS,
                     account_id: int = SODEX_ACCOUNT_ID) -> tuple[list[dict], list[dict], dict]:
    """
    Busca posições, ordens e saldo em uma única sessão HTTP compartilhada.
    Retorna: (positions, orders, account_dict)

    wallet_address/account_id identificam qual das contas (1 ou 2) buscar —
    por padrão, a Conta 1.
    """
    url    = f"{PERPS_ENDPOINT}/accounts/{wallet_address}/state"
    params = {"accountID": account_id} if account_id else {}

    async with aiohttp.ClientSession() as session:
        raw, mark_prices, market_precision = await asyncio.gather(
            _get_public(session, url, params=params),
            fetch_mark_prices(session),
            fetch_market_precision(session),
        )

    # Atualiza o cache global de precisão apenas quando a busca retorna algo
    # útil — evita apagar a precisão já conhecida caso o endpoint falhe
    # numa atualização pontual (ex.: instabilidade de rede).
    if market_precision:
        MARKET_PRECISION.update(market_precision)

    positions, orders = _parse_state(raw, mark_prices)

    trailing_counts = _read_bot_trailing_counts()
    for p in positions:
        p["trl"] = trailing_counts.get(p.get("symbol", ""), 0)

    acct = _parse_account(raw, positions)
    return positions, orders, acct


async def fetch_results(wallet_address: str = SODEX_WALLET_ADDRESS,
                         account_id: int = SODEX_ACCOUNT_ID) -> list[dict]:
    """
    Busca histórico de posições fechadas nos últimos 7 dias.
    GET /perps/accounts/{userAddress}/positions/history?startTime=...&limit=50

    wallet_address/account_id identificam qual das contas (1 ou 2) buscar —
    por padrão, a Conta 1.
    """
    since  = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
    url    = f"{PERPS_ENDPOINT}/accounts/{wallet_address}/positions/history"
    params = {"startTime": since, "limit": 50}
    if account_id:
        params["accountID"] = account_id
    async with aiohttp.ClientSession() as session:
        raw = await _get_public(session, url, params=params)
    return _parse_history(raw)


async def fetch_account(raw_state: Any, positions: list[dict]) -> dict:
    """
    Extrai saldo diretamente do raw JSON do /state (campo "B" e "av"/"am"/"im").
    Não faz chamada HTTP extra — reutiliza o payload já obtido.
    """
    return _parse_account(raw_state, positions)


async def fetch_tradefinder_signals() -> list[dict]:
    """
    Sinais do TradeFinder — mantidos como placeholder.
    A SoDEX não expõe sinais proprietários via API pública.
    """
    return []


# ═════════════════════════════════════════════════════════════════════════════
#  ARCUS (tecla [3]) — API REST pública, SOMENTE LEITURA
#  Portado do dashboard1.py. Documentação: https://docs.arcus.xyz/api-reference/introduction
#
#    GET /v1/account      saldo (equity, freeCollateral...) + posições abertas
#    GET /v1/openOrders   ordens abertas (OPEN) e TP/SL parados (UNTRIGGERED)
#    GET /v1/fills        fills com PnL realizado (closedPnl) — histórico de 7 dias
#    GET /v1/markets      tickSize (casas decimais) e markPrice de cada mercado
# ═════════════════════════════════════════════════════════════════════════════

REFRESH_SECS_ARCUS  = 3     # 3 requisições por ciclo; evita HTTP 429
RESULTS_EVERY_ARCUS = 10    # histórico de resultados: a cada 10 ciclos (~30s)
RESULTS_DAYS        = 7
FILLS_LIMIT         = 1000


async def _arcus_http_get(
    session: aiohttp.ClientSession,
    url: str,
    params: dict | list | None = None,
    headers: dict | None = None,
) -> Any:
    """GET na API da Arcus. Levanta aiohttp.ClientResponseError em HTTP >= 400."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    async with session.get(
        url,
        headers=hdrs,
        params=params,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def _arcus_get(session: aiohttp.ClientSession, path: str,
                     params: dict | list | None = None) -> Any:
    """GET em {ARCUS_REST_URL}{path}. Segundo a doc, as leituras não exigem autenticação;
    se a API responder 401/403 e houver chave pública derivada, repete com X-API-Key."""
    url = f"{ARCUS_REST_URL}{path}"
    try:
        return await _arcus_http_get(session, url, params)
    except aiohttp.ClientResponseError as e:
        if e.status in (401, 403) and ARCUS_API_KEY_PUB:
            return await _arcus_http_get(session, url, params, {"X-API-Key": ARCUS_API_KEY_PUB})
        raise


def _parse_markets(raw: Any) -> dict:
    """Extrai de /v1/markets: precisão (casas decimais), mark price, tick e step por símbolo."""
    out: dict[str, dict] = {"precision": {}, "marks": {}, "ticks": {}, "steps": {}}
    items = raw.get("markets", []) if isinstance(raw, dict) else []
    for m in items:
        if not isinstance(m, dict):
            continue
        name = str(m.get("marketDisplayName") or m.get("symbol") or m.get("name") or "")
        if not name:
            continue
        if m.get("tickSize") is not None:
            dec = _decimals_from_tick(m["tickSize"])
            if dec is not None:
                out["precision"][name] = dec
            if _safe_float(m["tickSize"]) > 0:
                out["ticks"][name] = _safe_float(m["tickSize"])
        if _safe_float(m.get("stepSize")) > 0:
            out["steps"][name] = _safe_float(m["stepSize"])
        # markPrice "0" = ainda sem mark (a doc manda NÃO cair para o oraclePrice nesse caso)
        px = _safe_float(m.get("markPrice")) if "markPrice" in m else _safe_float(m.get("oraclePrice"))
        if px > 0:
            out["marks"][name] = px
    return out


def _parse_arcus_state(account: dict, orders_raw: Any, mk: dict) -> tuple[list[dict], list[dict]]:
    """
    Extrai posições abertas e ordens pendentes.

    ── Posição (GET /v1/account → positions{marketId: {...}}) ─────────────────
      marketDisplayName  símbolo (ex.: "BTC-USD")
      side               LONG | SHORT
      size / averageEntryPrice   ATENÇÃO: vêm em unidades do engine (ticks/quantums),
                                 não em decimal — por isso NÃO são usados diretamente.
      positionValueNotional  nocional assinado ao mark = tamanho × mark (decimal)
      borrowedCapital        custo-base assinado = −tamanho × preço de entrada (decimal)
      markPx                 mark price (decimal)
      marginUsed             margem alocada (decimal)

      Derivados (tudo em decimal, sem depender da escala do engine):
        tamanho  = |positionValueNotional| / markPx
        entrada  = |borrowedCapital| / tamanho
        uPnL     = positionValueNotional + borrowedCapital
      (o campo `unrealizedPnl` da Arcus é uma variação de MARGEM, não o PnL de preço;
       por isso só é usado como último recurso)

    ── Ordem (GET /v1/openOrders → orders[]) ──────────────────────────────────
      orderId, marketDisplayName, side (BUY|SELL), price, originalSize, remainingSize
      tpslType (STOP_LOSS | TAKE_PROFIT) + triggerPrice → TP/SL parados (UNTRIGGERED)
      parentOrderId → TP/SL criado junto com uma ordem de entrada
      isPositionTPSL → TP/SL que fecha a posição inteira (no máx. 1 TP e 1 SL por mercado)
    """
    marks = mk.get("marks", {})
    steps = mk.get("steps", {})
    ticks = mk.get("ticks", {})

    raw_orders = orders_raw.get("orders", []) if isinstance(orders_raw, dict) else []
    raw_orders = [o for o in raw_orders if isinstance(o, dict)]

    # ── Indexa TP/SL ────────────────────────────────────────────────────────
    # TP/SL cujo pai (entrada) ainda está na lista pertence à ORDEM PENDENTE;
    # os demais (posição inteira ou pernas parciais) pertencem à POSIÇÃO do símbolo.
    plain_ids = {str(o.get("orderId")) for o in raw_orders if not o.get("tpslType")}
    tp_by_parent: dict[str, float] = {}
    sl_by_parent: dict[str, float] = {}
    tp_by_symbol: dict[str, float] = {}
    sl_by_symbol: dict[str, float] = {}

    for o in raw_orders:
        kind = str(o.get("tpslType") or "").upper()
        if kind not in ("TAKE_PROFIT", "STOP_LOSS"):
            continue
        trig = _safe_float(o.get("triggerPrice"))
        if trig <= 0:
            continue
        is_tp  = kind == "TAKE_PROFIT"
        symbol = str(o.get("marketDisplayName") or "")
        parent = o.get("parentOrderId")
        if parent is not None and str(parent) in plain_ids:
            (tp_by_parent if is_tp else sl_by_parent)[str(parent)] = trig
        else:
            target = tp_by_symbol if is_tp else sl_by_symbol
            # lista vem do mais novo p/ o mais antigo; o TP/SL de posição inteira tem prioridade
            if symbol not in target or o.get("isPositionTPSL"):
                target[symbol] = trig

    # ── Posições ────────────────────────────────────────────────────────────
    raw_positions = account.get("positions") or {}
    items = list(raw_positions.values()) if isinstance(raw_positions, dict) else list(raw_positions)

    positions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_size = _safe_float(item.get("size"))
        if raw_size == 0.0:
            continue  # posição zerada — ignora

        symbol    = str(item.get("marketDisplayName") or item.get("marketId") or "???")
        par       = symbol.split("-")[0].upper()
        side      = str(item.get("side") or "").upper()
        direction = side if side in ("LONG", "SHORT") else ("LONG" if raw_size > 0 else "SHORT")

        notional   = _safe_float(item.get("positionValueNotional"))   # assinado
        has_bc     = item.get("borrowedCapital") is not None
        borrowed   = _safe_float(item.get("borrowedCapital"))         # assinado
        mark_px    = _safe_float(item.get("markPx"))
        mark       = mark_px or marks.get(symbol, 0.0)

        # tamanho em unidades do ativo
        if mark_px > 0 and notional != 0.0:
            size_h = abs(notional) / mark_px
        else:                                   # sem mark no snapshot: escala o inteiro do engine
            size_h = abs(raw_size) * steps.get(symbol, 1.0)

        # preço de entrada
        if has_bc and borrowed != 0.0 and size_h > 0:
            entry = abs(borrowed) / size_h
        else:
            raw_entry = str(item.get("averageEntryPrice") or "")
            entry = _safe_float(raw_entry)
            if entry and "." not in raw_entry and ticks.get(symbol):
                entry *= ticks[symbol]          # inteiro em ticks → decimal
        mark = mark or entry

        # PnL não realizado (diferença de preço)
        if has_bc and mark_px > 0 and notional != 0.0:
            upnl = notional + borrowed
        elif mark > 0 and entry > 0 and size_h > 0:
            upnl = size_h * (mark - entry) * (1 if direction == "LONG" else -1)
        else:
            upnl = _safe_float(item.get("unrealizedPnl"))

        try:
            leverage = int(float(item.get("leverage") or 1)) or 1
        except (TypeError, ValueError):
            leverage = 1

        positions.append({
            "par":           par,
            "symbol":        symbol,
            "pos_id":        item.get("marketId"),
            "dir":           direction,
            "pnl":           round(upnl, 4),
            "upnl":          round(upnl, 4),
            "realizedPnl":   0.0,
            # Mantém mais casas que o necessário de propósito — quem decide as casas
            # decimais exibidas é _fmt_price(), usando a precisão oficial.
            "preco":         round(mark, 8),
            "entry":         round(entry, 8),
            "size":          size_h if direction == "LONG" else -size_h,
            "leverage":      leverage,
            "liq_price":     0.0,
            "tp":            tp_by_symbol.get(symbol),
            "sl":            sl_by_symbol.get(symbol),
            "trl":           0,
            "owner":         "bot",
            "initialMargin": _safe_float(item.get("marginUsed")),
        })

    # ── Ordens pendentes (não-TP/SL) ────────────────────────────────────────
    orders = []
    for o in raw_orders:
        if o.get("tpslType"):
            continue  # TP/SL já aparece vinculado à posição / ordem pai
        symbol  = str(o.get("marketDisplayName") or "???")
        par     = symbol.split("-")[0].upper()
        price   = _safe_float(o.get("price"))
        size    = _safe_float(o["remainingSize"] if o.get("remainingSize") is not None
                              else o.get("originalSize"))
        oid     = str(o.get("orderId"))
        orders.append({
            "par":     par,
            "symbol":  symbol,
            "side":    str(o.get("side") or "").upper(),     # BUY | SELL
            "entrada": price,
            "mark":    marks.get(symbol, 0.0),
            # Sem fallback por símbolo: TP/SL só aparece aqui se estiver ligado a ESTA
            # ordem (parentOrderId); caso contrário o campo fica vazio ("----").
            "tp":      tp_by_parent.get(oid, 0.0),
            "sl":      sl_by_parent.get(oid, 0.0),
            "size":    round(abs(size) * price, 2),          # nocional
        })

    return positions, orders


def _parse_arcus_account(account: dict | None, positions: list[dict]) -> dict:
    """
    Saldo da conta a partir de GET /v1/account.

      equity          = netQuoteBalance + Σ(tamanho × oracle)  → já INCLUI o PnL não realizado
      freeCollateral  = equity − Σ margem inicial
      margem em uso   = equity − freeCollateral  (mesmo cálculo do check_setup.py)
    """
    if not account:  # 404: conta ainda sem atividade
        return {"total": 0.0, "available": 0.0, "margin": 0.0, "upnl": 0.0, "empty": True}

    equity = _safe_float(account.get("equity"))
    if account.get("freeCollateral") is not None:
        free   = _safe_float(account.get("freeCollateral"))
        margin = max(equity - free, 0.0)
    else:
        margin = sum(p.get("initialMargin", 0.0) for p in positions)
        free   = max(equity - margin, 0.0)

    return {
        "total":               round(equity, 2),
        "available":           round(free, 2),
        "margin":              round(margin, 2),
        "upnl":                round(sum(p.get("upnl", 0.0) for p in positions), 2),
        "pending_deposits":    round(_safe_float(account.get("pendingDeposits")), 2),
        "pending_withdrawals": round(_safe_float(account.get("pendingWithdrawals")), 2),
    }


def _parse_fills(raw: Any) -> list[dict]:
    """
    Converte fills (GET /v1/fills) em "posições fechadas" dos últimos 7 dias.

    Só entram fills que FECHAM posição (positionEffect CLOSE_* / FLIP_*, ou fechamento
    forçado por liquidação/ADL). Fills de abertura carregam apenas −fee em `closedPnl` e
    não aparecem como linha. Fills da mesma ordem (orderId) são somados numa linha só.

      closedPnl  → PnL realizado do fill, já líquido da taxa
      positionEffect  CLOSE_LONG / FLIP_LONG_TO_SHORT  → fechou um LONG
                      CLOSE_SHORT / FLIP_SHORT_TO_LONG → fechou um SHORT
    """
    fills = raw.get("fills", []) if isinstance(raw, dict) else []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RESULTS_DAYS)

    by_order: dict[str, dict] = {}   # dict preserva a ordem (mais novo primeiro)
    for f in fills:
        if not isinstance(f, dict):
            continue
        ts_raw = f.get("createdAt")
        if ts_raw:
            try:
                if datetime.fromtimestamp(int(ts_raw) / 1_000_000, tz=timezone.utc) < cutoff:
                    continue
            except Exception:
                pass

        eff = str(f.get("positionEffect") or "").upper()
        pnl = _safe_float(f.get("closedPnl"))
        side = str(f.get("side") or "").upper()

        if eff:
            is_close = eff.startswith(("CLOSE", "FLIP")) or bool(f.get("liquidation"))
        else:  # linhas antigas sem positionEffect: abertura tem closedPnl == −fee
            is_close = abs(pnl + _safe_float(f.get("fee"))) > 1e-12
        if not is_close:
            continue

        if eff in ("CLOSE_LONG", "FLIP_LONG_TO_SHORT"):
            direction = "LONG"
        elif eff in ("CLOSE_SHORT", "FLIP_SHORT_TO_LONG"):
            direction = "SHORT"
        else:  # SELL fecha LONG; BUY fecha SHORT
            direction = "LONG" if side == "SELL" else "SHORT"

        symbol = str(f.get("marketDisplayName") or "???")
        key    = str(f.get("orderId") or f.get("tradeId") or id(f))
        size   = abs(_safe_float(f.get("size")))
        price  = _safe_float(f.get("price"))

        row = by_order.setdefault(key, {"par": symbol.split("-")[0].upper(), "dir": direction,
                                        "pnl": 0.0, "_sz": 0.0, "_notional": 0.0})
        row["pnl"]       += pnl
        row["_sz"]       += size
        row["_notional"] += size * price

    results = []
    for row in by_order.values():
        px = row["_notional"] / row["_sz"] if row["_sz"] else 0.0
        results.append({
            "par":         row["par"],
            "dir":         row["dir"],
            "pnl":         round(row["pnl"], 4),
            "close_price": round(px, 4) if px else None,
        })
    return results


def _arcus_address_variants() -> list[str]:
    """Endereço em minúsculas (forma normalizada da API) e, se diferente, como está no .env."""
    w = ARCUS_WALLET_ADDRESS
    return [w.lower()] + ([w] if w != w.lower() else [])


# Subconta definida no .env (guardada para o aviso no cabeçalho caso seja trocada).
ARCUS_ACCOUNT_INDEX_ENV = ARCUS_ACCOUNT_INDEX
_ARCUS_ACCOUNT_INDEX_RESOLVED = False


async def _resolve_arcus_account_index(session: aiohttp.ClientSession) -> None:
    """Roda UMA vez. Se a subconta do .env responde 404 (sem atividade), procura nas
    demais (0-9) e passa a usar a que tem posições abertas (ou, na falta, a primeira
    com atividade). Cada índice é um silo isolado na Arcus: posições e saldo de uma
    subconta nunca aparecem na consulta de outra."""
    global ARCUS_ACCOUNT_INDEX, _ARCUS_ACCOUNT_INDEX_RESOLVED
    addr = ARCUS_WALLET_ADDRESS.lower()

    async def _probe(idx: int) -> dict | None:
        try:
            raw = await _arcus_get(session, "/v1/account",
                                   {"address": addr, "accountIndex": idx})
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise
        return raw if isinstance(raw, dict) else None

    if await _probe(ARCUS_ACCOUNT_INDEX) is not None:
        _ARCUS_ACCOUNT_INDEX_RESOLVED = True      # subconta do .env OK — nada a fazer
        return

    found: list[tuple[int, bool]] = []      # (índice, tem posição aberta)
    for idx in range(10):
        if idx == ARCUS_ACCOUNT_INDEX:
            continue
        await asyncio.sleep(0.25)           # espaça as consultas (evita HTTP 429)
        raw = await _probe(idx)
        if raw is not None:
            has_pos = any(isinstance(p, dict) and _safe_float(p.get("size")) != 0.0
                          for p in (raw.get("positions") or {}).values())
            found.append((idx, has_pos))

    _ARCUS_ACCOUNT_INDEX_RESOLVED = True
    if found:
        with_pos = [i for i, has in found if has]
        ARCUS_ACCOUNT_INDEX = (with_pos or [i for i, _ in found])[0]


async def _fetch_arcus_account_raw(session: aiohttp.ClientSession) -> dict | None:
    """GET /v1/account. Retorna None se a conta ainda não tem atividade (404)."""
    for addr in _arcus_address_variants():
        try:
            raw = await _arcus_get(session, "/v1/account",
                                   {"address": addr, "accountIndex": ARCUS_ACCOUNT_INDEX})
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                continue
            raise
        if isinstance(raw, dict):
            return raw
        raise ValueError("resposta inesperada da Arcus em /v1/account")
    return None


async def fetch_all_arcus() -> tuple[list[dict], list[dict], dict]:
    """
    Busca conta, ordens abertas e mercados em paralelo, numa única sessão HTTP.
    Retorna: (positions, orders, account_dict) — mesmo formato de fetch_all().
    """
    if ARCUS_CONFIG_ERRORS:
        raise RuntimeError("Arcus (.env): " + "; ".join(ARCUS_CONFIG_ERRORS))
    addr = ARCUS_WALLET_ADDRESS.lower()
    if not _ARCUS_ACCOUNT_INDEX_RESOLVED:
        async with aiohttp.ClientSession() as _s:
            await _resolve_arcus_account_index(_s)
    open_orders_params = [
        ("address", addr), ("accountIndex", ARCUS_ACCOUNT_INDEX),
        ("status", "OPEN"), ("status", "UNTRIGGERED"),
    ]
    async with aiohttp.ClientSession() as session:
        acct_raw, orders_raw, markets_raw = await asyncio.gather(
            _fetch_arcus_account_raw(session),
            _arcus_get(session, "/v1/openOrders", open_orders_params),
            _arcus_get(session, "/v1/markets"),
            return_exceptions=True,
        )

    # conta e ordens são essenciais; mercados só refinam precisão/mark (falha tolerada)
    for r in (acct_raw, orders_raw):
        if isinstance(r, BaseException):
            raise r
    if isinstance(markets_raw, BaseException):
        markets_raw = {}

    mk = _parse_markets(markets_raw)
    # Só atualiza o cache de precisão quando a busca retorna algo útil.
    if mk["precision"]:
        ARCUS_MARKET_PRECISION.update(mk["precision"])

    positions, orders = _parse_arcus_state(acct_raw or {}, orders_raw, mk)

    trailing_counts = _read_bot_trailing_counts()
    for p in positions:
        p["trl"] = trailing_counts.get(p.get("symbol", ""), 0)

    acct = _parse_arcus_account(acct_raw, positions)
    return positions, orders, acct


async def fetch_results_arcus() -> list[dict]:
    """
    Histórico de posições fechadas nos últimos 7 dias, via GET /v1/fills.
    `from` é em MICROSSEGUNDOS (a API rejeita segundos/milissegundos).
    """
    since = int((datetime.now(timezone.utc) - timedelta(days=RESULTS_DAYS)).timestamp() * 1_000_000)
    params = {"address": ARCUS_WALLET_ADDRESS.lower(), "accountIndex": ARCUS_ACCOUNT_INDEX,
              "from": since, "limit": FILLS_LIMIT}
    async with aiohttp.ClientSession() as session:
        raw = await _arcus_get(session, "/v1/fills", params)
    return _parse_fills(raw)


# ─────────────────────────────────────────────────────────────────────────────
#  RENDERIZADORES RICH
# ─────────────────────────────────────────────────────────────────────────────

def _col(text: str, color: str) -> Text:
    return Text(str(text), style=color)


def _fmt_price(value: float | None, symbol: str | None = None) -> str:
    """Formata o preço/valor de um ativo com o número de casas decimais
    definido pela própria SoDEX para aquele símbolo (MARKET_PRECISION,
    populado via GET /perps/markets/symbols).

    Se a precisão do símbolo não estiver disponível (ex.: endpoint de
    mercados ainda não respondeu, ou símbolo desconhecido), cai para a
    heurística anterior:
    - valor >= 1 USDC  → 2 casas decimais
    - valor <  1 USDC  → 5 casas decimais (ativos de preço muito baixo,
      ex.: shitcoins, precisam de mais precisão para não zerar na exibição)
    """
    if value is None:
        return "----"
    _table   = ARCUS_MARKET_PRECISION if _ACTIVE_VENUE == "arcus" else MARKET_PRECISION
    decimals = _table.get(symbol) if symbol else None
    if decimals is None:
        decimals = 2 if abs(value) >= 1 else 5
    return f"{value:,.{decimals}f}"


def _dir_text(direction: str) -> Text:
    clr = C["long"] if direction == "LONG" else C["short"]
    return Text(direction, style=f"bold {clr}")


def _pnl_text(pnl: float) -> Text:
    clr  = C["profit"] if pnl >= 0 else C["loss"]
    sign = "+" if pnl >= 0 else ""
    return Text(f"{sign}{pnl:.2f}", style=f"bold {clr}")


def _pnl_pct_text(pnl: float, size: float, entry_px: float) -> Text:
    """PNL em USDC e, na linha abaixo, o percentual em relação ao valor da posição
    aberta (|size| * preço de entrada)."""
    notional = abs(size) * entry_px if entry_px else 0.0
    pct  = (pnl / notional * 100) if notional else 0.0
    clr  = C["profit"] if pnl >= 0 else C["loss"]
    sign = "+" if pnl >= 0 else ""
    return Text(f"{sign}{pnl:.2f}\n({sign}{pct:.2f}%)", style=f"bold {clr}")


def render_positions(positions: list[dict]) -> Panel:
    # Ordena por símbolo para manter posição estável entre atualizações
    positions = sorted(positions, key=lambda p: p.get("symbol", ""))
    tbl = Table(
        box=rbox.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C['title']} on {C['panel_bg']}",
        style=C["text"],
        expand=True,
        border_style=C["border"],
        pad_edge=False,
        show_edge=False,
        row_styles=["", f"on {C['row_shade']}"],
    )
    tbl.add_column("ATIVO",    style=C["cyan"],    width=8,  no_wrap=True)
    tbl.add_column("DIR",    width=4,             no_wrap=True)
    tbl.add_column("PNL",    width=9,            no_wrap=True)
    tbl.add_column("ENTRADA",style=C["dim"],     width=8, no_wrap=True)
    tbl.add_column("MARKET",   style=C["text"],    width=8, no_wrap=True)
    tbl.add_column("TAKE PROFIT",     style=C["tp_col"],  width=12, no_wrap=True)
    tbl.add_column("STOP LOSS",     style=C["sl_col"],  width=12, no_wrap=True)
    tbl.add_column("SIZE",   style=C["orange"],  width=10, no_wrap=True)

    for p in positions:
        entry_px = p.get('entry', p['preco'])
        symbol   = p.get('symbol')
        if p.get("tp") and entry_px:
            tp_pct = (p['tp'] - entry_px) / entry_px * 100
            tp_s   = f"{_fmt_price(p['tp'], symbol)}\n({tp_pct:+.2f}%)"
        else:
            tp_s = "----"
        if p.get("sl") and entry_px:
            sl_pct = (p['sl'] - entry_px) / entry_px * 100
            sl_s   = f"{_fmt_price(p['sl'], symbol)}\n({sl_pct:+.2f}%)"
            # SL já em lucro → destaca em verde (ex.: trailing stop já
            # protegendo lucro). Para LONG, lucro = SL acima da entrada;
            # para SHORT, lucro = SL abaixo da entrada. Caso contrário,
            # mantém a cor padrão.
            direction = p.get("dir", "LONG")
            if direction == "SHORT":
                sl_in_profit = p['sl'] < entry_px
            else:
                sl_in_profit = p['sl'] > entry_px
            sl_color = C["green"] if sl_in_profit else C["sl_col"]
        else:
            sl_s = "----"
            sl_color = C["sl_col"]
        entry_s = _fmt_price(entry_px, symbol)
        mark_s  = _fmt_price(p['preco'], symbol)
        notional = abs(p.get("size", 0.0)) * p.get("preco", 0.0)
        size_s  = f"{notional:,.2f}"

        tbl.add_row(
            _col(p["par"], C["cyan"]),
            _dir_text(p["dir"]),
            _pnl_pct_text(p["pnl"], p.get("size", 0.0), entry_px),
            _col(entry_s, C["dim"]),
            _col(mark_s,  C["text"]),
            _col(tp_s, C["tp_col"]),
            _col(sl_s, sl_color),
            _col(size_s, C["orange"]),
        )

    if not positions:
        tbl.add_row(
            Text("—", style=C["dim"]),
            Text("Sem p…", style=C["dim"]),
            Text(""), Text(""), Text(""), Text(""), Text(""), Text(""), Text(""), Text(""), Text(""),
        )

    return Panel(
        tbl,
        title=f"[bold {C['title']}]● POSIÇÕES[/]",
        border_style=C["border"],
        padding=(0, 1),
    )


def render_pending_orders(orders: list[dict]) -> Panel:
    tbl = Table(
        box=rbox.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C['title']} on {C['panel_bg']}",
        style=C["text"],
        expand=True,
        border_style=C["border"],
        pad_edge=False,
        show_edge=False,
        row_styles=["", f"on {C['row_shade']}"],
    )
    tbl.add_column("ATIVO",     style=C["yellow"], width=8,  no_wrap=True)
    tbl.add_column("DIR",     width=4,            no_wrap=True)
    tbl.add_column("ENTRADA", style=C["dim"],    width=8,  no_wrap=True)
    tbl.add_column("MARKET",    style=C["text"],   width=8,  no_wrap=True)
    tbl.add_column("TAKE PROFIT",      style=C["tp_col"], width=12,  no_wrap=True)
    tbl.add_column("STOP LOSS",      style=C["sl_col"], width=12,  no_wrap=True)
    tbl.add_column("SIZE",    style=C["orange"], width=10,  no_wrap=True)

    for o in orders:
        side      = o.get("side", "")
        direction = "LONG" if side == "BUY" else "SHORT" if side == "SELL" else side
        side_txt  = _dir_text(direction) if direction in ("LONG", "SHORT") \
              else Text(direction, style=C["dim"])
        symbol    = o.get('symbol')
        entrada   = o.get("entrada") or 0.0
        if o.get("tp") and entrada:
            tp_pct = (o['tp'] - entrada) / entrada * 100
            tp_s   = f"{_fmt_price(o['tp'], symbol)}\n({tp_pct:+.2f}%)"
        else:
            tp_s = _fmt_price(o['tp'], symbol) if o.get("tp") else "----"
        if o.get("sl") and entrada:
            sl_pct = (o['sl'] - entrada) / entrada * 100
            sl_s   = f"{_fmt_price(o['sl'], symbol)}\n({sl_pct:+.2f}%)"
        else:
            sl_s = _fmt_price(o['sl'], symbol) if o.get("sl") else "----"
        entrada_s = _fmt_price(o['entrada'], symbol) if o.get("entrada") else "----"
        mark_s    = _fmt_price(o['mark'], symbol)    if o.get("mark")    else "----"
        tbl.add_row(
            _col(o["par"],    C["yellow"]),
            side_txt,
            _col(entrada_s,   C["dim"]),
            _col(mark_s,      C["text"]),
            _col(tp_s,        C["tp_col"]),
            _col(sl_s,        C["sl_col"]),
            _col(f"{o['size']:,.2f}", C["orange"]),
        )

    if not orders:
        tbl.add_row(
            Text("—", style=C["dim"]),
            Text("Sem or…", style=C["dim"]),
            Text(""), Text(""), Text(""), Text(""),
        )

    return Panel(
        tbl,
        title=f"[bold {C['pending']}]◐ ORDENS PENDENTES[/]",
        border_style=C["border"],
        padding=(0, 1),
    )


def render_tradefinder(signals: list[dict]) -> Panel:
    tbl = Table(
        box=rbox.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C['header']}",
        style=C["text"],
        expand=True,
        border_style=C["border"],
        pad_edge=False,
        show_edge=False,
    )
    tbl.add_column("PAR",     style=C["cyan"],   width=6,  no_wrap=True)
    tbl.add_column("SINAL",   width=7,            no_wrap=True)
    tbl.add_column("ENTRADA", style=C["text"],   width=8,  no_wrap=True)
    tbl.add_column("TP %",    style=C["tp_col"], width=7,  no_wrap=True)
    tbl.add_column("SL %",    style=C["sl_col"], width=7,  no_wrap=True)
    tbl.add_column("HORA",    style=C["dim"],    width=6,  no_wrap=True)

    for s in signals:
        tbl.add_row(
            _col(s["par"],               C["cyan"]),
            _dir_text(s["sinal"]),
            _col(f"${_fmt_price(s['entrada'])}", C["text"]),
            _col(f"{s['tp_pct']:.1f}%",  C["tp_col"]),
            _col(f"{s['sl_pct']:.1f}%",  C["sl_col"]),
            _col(s["ts"],                C["dim"]),
        )

    if not signals:
        tbl.add_row(
            Text("—", style=C["dim"]),
            Text("Sem sinais hoje", style=C["dim"]),
            Text(""), Text(""), Text(""), Text(""),
        )

    return Panel(
        tbl,
        title=f"[bold {C['signal']}]◈ TRADEFINDER — Sinais do Dia[/]",
        border_style=C["border"],
        padding=(0, 1),
    )


def render_results(results: list[dict]) -> Panel:
    tbl = Table(
        box=rbox.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C['title']} on {C['panel_bg']}",
        style=C["text"],
        expand=True,
        border_style=C["border"],
        pad_edge=False,
        show_edge=False,
        row_styles=["", f"on {C['row_shade']}"],
    )
    tbl.add_column("ATIVO",         width=8, no_wrap=True)
    tbl.add_column("DIR",           width=10,  no_wrap=True)
    tbl.add_column("PNL",           width=13, no_wrap=True)

    total_pnl  = 0.0
    wins = losses = 0

    for r in results:
        pnl  = r["pnl"]
        total_pnl += pnl
        if pnl >= 0:
            wins += 1
            icon = Text("✅ ", style=C["green"])
        else:
            losses += 1
            icon = Text("❌ ", style=C["red"])

        par_txt = Text()
        par_txt.append_text(icon)
        par_txt.append(r["par"], style=C["cyan"])

        tbl.add_row(
            par_txt,
            _dir_text(r["dir"]),
            _pnl_text(pnl),
        )

    if not results:
        tbl.add_row(
            Text("—", style=C["dim"]),
            Text("Sem op. fechadas", style=C["dim"]),
            Text(""),
        )
    else:
        # Linha separadora + Total no final da tabela
        tbl.add_section()
        sign  = "+" if total_pnl >= 0 else ""
        color = C["profit"] if total_pnl >= 0 else C["loss"]
        total_label   = Text("TOTAL", style=f"bold {C['dim']}")
        wl_txt        = Text(f"{wins}W / {losses}L", style=C["dim"])
        total_pnl_txt = Text(f"{sign}{total_pnl:.4f}", style=f"bold {color}")
        tbl.add_row(total_label, wl_txt, total_pnl_txt)

    return Panel(
        tbl,
        title=f"[bold {C['magenta']}]◎ Resultado — Últimos 7 dias[/]",
        border_style=C["border"],
        padding=(0, 1),
    )


def render_account(acct: dict, last_update: str, label: str = "",
                   venue: str = "SoDEX", currency: str = "USDC") -> Panel:
    def row(label: str, value: float, color: str = C["text"], decimals: int = 2) -> Text:
        t = Text()
        t.append(f"  {label:<15}", style=C["dim"])
        fmt = f"{{:>5,.{decimals}f}}"
        t.append(fmt.format(value) + f" {currency}", style=f"bold {color}")
        return t

    upnl       = acct.get("upnl", 0.0)
    upnl_color = C["profit"] if upnl >= 0 else C["loss"]
    sign       = "+" if upnl >= 0 else ""

    lines = Text()
    lines.append_text(row("Saldo Total:",     acct.get("total",     0.0), C["cyan"]))
    lines.append("\n")
    lines.append_text(row("Disponível:",       acct.get("available", 0.0), C["green"]))
    lines.append("\n")
    lines.append_text(row("Margem em uso:",   acct.get("margin",    0.0), C["yellow"]))
    lines.append("\n")
    lines.append(f"  {'PnL não realizado:':<17}", style=C["dim"])
    lines.append(f"{sign}{upnl:>5,.2f} {currency}", style=f"bold {upnl_color}")

    # Linhas extras da Arcus — só aparecem quando há o dado (não alteram a SoDEX)
    if acct.get("pending_deposits"):
        lines.append("\n")
        lines.append_text(row("Dep. pend.:", acct["pending_deposits"], C["dim"]))
    if acct.get("pending_withdrawals"):
        lines.append("\n")
        lines.append_text(row("Saq. pend.:", acct["pending_withdrawals"], C["dim"]))
    if acct.get("empty"):
        lines.append("\n")
        lines.append("  Conta sem atividade ainda (404).", style=C["yellow"])

    title_suffix = f" — {label}" if label else ""
    return Panel(
        lines,
        title=f"[bold {C['title']}]💼 Conta {venue}{title_suffix}[/]",
        border_style=C["border"],
        padding=(0, 1),
    )


def render_status_bar(tick: int, last_error: str = "") -> Text:
    dots = "." * (tick % 4)
    t    = Text()
    t.append("  SoDEX Bot  ", style=f"bold {C['title']}")
    t.append("│", style=C["dim"])
    t.append(f"  Wallet: {SODEX_WALLET_ADDRESS[:10]}…  ", style=C["dim"])
    t.append("│", style=C["dim"])
    if last_error:
        t.append(f"  ⚠ {last_error[:70]}", style=f"bold {C['red']}")
    else:
        t.append(f"  Próxima atualização{dots:<3}", style=C["dim"])
    return t


# ─────────────────────────────────────────────────────────────────────────────
#  WIDGETS TEXTUAL
# ─────────────────────────────────────────────────────────────────────────────

class PanelWidget(Static):
    """Widget genérico que recebe um Rich renderable e o exibe."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
#  APP PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_CSS = """
Screen {
    background: #1a1b26;
    layout: vertical;
}

#header-bar {
    height: 1;
    background: #1e2030;
    color: #7dcfff;
    padding: 0 1;
    text-style: bold;
}
#main-layout {
    layout: horizontal;
    height: 1fr;
}

#left-col {
    layout: vertical;
    width: 2fr;
}

#right-col {
    layout: vertical;
    width: 40;
}

#positions-panel {
    height: 2fr;
    margin: 0 0 0 0;
}

#bottom-row {
    layout: vertical;
    height: 1fr;
}

#pending-panel {
    height: 1fr;
}
#account-panel {
    height: auto;
    margin: 0 0 1 0;
}

#results-panel {
    height: 1fr;
}

PanelWidget {
    padding: 0;
    margin: 0;
}
"""


class SoDEXDashboard(App):
    """Dashboard TUI estilo btop para o SoDEX Trading Bot."""

    CSS      = DASHBOARD_CSS
    TITLE    = "SoDEX Trading Bot"
    BINDINGS = [
        ("q", "quit",    "Sair"),
        ("r", "refresh", "Atualizar"),
        ("1", "select_account('1')", "Conta 1"),
        ("2", "select_account('2')", "Conta 2"),
        ("3", "select_account('3')", "Arcus"),
    ]

    _positions:   reactive[list] = reactive([], layout=True)
    _orders:      reactive[list] = reactive([], layout=True)
    _signals:     reactive[list] = reactive([], layout=True)
    _results:     reactive[list] = reactive([], layout=True)
    _account:     reactive[dict] = reactive({},  layout=True)
    _last_update: reactive[str]  = reactive("--:--:--")
    _last_error:  reactive[str]  = reactive("")
    _tick:        reactive[int]  = reactive(0)
    _results_tick: int           = 0   # contador para throttle do histórico
    _active_account: reactive[int] = reactive(1)  # 1, 2 ou 3 (Arcus) — qual API está sendo exibida
    _results_loaded: bool        = False  # Arcus: já buscou o histórico alguma vez?
    _rate_limited:   bool        = False  # Arcus: última resposta foi HTTP 429? (espaça o loop)

    def compose(self) -> ComposeResult:
        yield Static(self._build_header(self._last_update), id="header-bar")
        with Horizontal(id="main-layout"):
            with Vertical(id="left-col"):
                yield PanelWidget(id="positions-panel")
                with Vertical(id="bottom-row"):
                    yield PanelWidget(id="pending-panel")
            with Vertical(id="right-col"):
                yield PanelWidget(id="account-panel")
                yield PanelWidget(id="results-panel")


    def _build_header(self, last_update: str = "--:--:--") -> Text:
        acc = ACCOUNTS[self._active_account]
        t = Text()
        if acc.get("venue") == "arcus":
            w = ARCUS_WALLET_ADDRESS
            short_w = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
            t.append(" ◆ Arcus Bot ", style=f"bold {C['title']}")
            t.append("│", style=C["dim"])
            t.append(
                f" [{ARCUS_ENV or '?'}] Subconta: {ARCUS_ACCOUNT_INDEX}"
                + (f" (.env: {ARCUS_ACCOUNT_INDEX_ENV})"
                   if ARCUS_ACCOUNT_INDEX != ARCUS_ACCOUNT_INDEX_ENV else "")
                + f" │ {short_w} │ {last_update}",
                style=C["text"],
            )
        else:
            t.append(" ◆ SoDEX Bot ", style=f"bold {C['title']}")
            t.append("│", style=C["dim"])
            t.append(
                f" [{acc['label']}] API: {acc['public_key']} │ Conta: {acc['account_id']} │ "
                f"{acc['wallet']} │ {last_update}",
                style=C["text"],
            )
        t.append("│", style=C["dim"])
        t.append(" [1] Conta 1  [2] Conta 2  [3] Arcus  [Q] Sair  [R] Atualizar", style=C["dim"])
        return t

    def on_mount(self) -> None:
        self._start_refresh_loop()

    @work(exclusive=False)
    async def _start_refresh_loop(self) -> None:
        """Loop de atualização contínua a cada REFRESH_SECS segundos."""
        while True:
            await self._do_refresh_once()
            if ACCOUNTS[self._active_account].get("venue") == "arcus":
                # Arcus: ciclo de 3s, espaçado ×5 enquanto responder HTTP 429
                await asyncio.sleep(REFRESH_SECS_ARCUS * (5 if self._rate_limited else 1))
            else:
                await asyncio.sleep(REFRESH_SECS)

    async def _do_refresh_once(self) -> None:
        """Busca todos os dados (da conta atualmente ativa) e atualiza os painéis."""
        global _ACTIVE_VENUE
        acc = ACCOUNTS[self._active_account]
        is_arcus = acc.get("venue") == "arcus"
        _ACTIVE_VENUE = "arcus" if is_arcus else "sodex"
        try:
            # fetch_all faz uma única sessão HTTP: /state + mark_prices em paralelo
            # e extrai posições, ordens e conta do mesmo payload — sem inconsistência.
            if is_arcus:
                pos, orders, acct = await fetch_all_arcus()
            else:
                pos, orders, acct = await fetch_all(acc["wallet"], acc["account_id"])

            # Histórico é pesado e raramente muda — atualiza a cada ~30s (15 ciclos de 2s;
            # Arcus: 10 ciclos de 3s)
            self._results_tick += 1
            if is_arcus:
                need_hist = self._results_tick >= RESULTS_EVERY_ARCUS or not self._results_loaded
            else:
                need_hist = self._results_tick >= 15 or not self._results
            if need_hist:
                try:
                    if is_arcus:
                        results = await fetch_results_arcus()
                        self._results_loaded = True
                    else:
                        results = await fetch_results(acc["wallet"], acc["account_id"])
                    self._results_tick = 0
                except Exception as e_hist:
                    results = list(self._results)
                    self.notify(f"Histórico: {str(e_hist)[:50]}", severity="warning", timeout=3)
            else:
                results = list(self._results)

            now = datetime.now().strftime("%H:%M:%S")

            self._positions   = list(pos)
            self._orders      = list(orders)
            self._account     = dict(acct)
            self._results     = list(results)
            self._last_update = now
            self._last_error  = ""
            self._rate_limited = False
            self._render_all()
        except aiohttp.ClientResponseError as e:
            self._rate_limited = is_arcus and e.status == 429
            self._last_error = (f"HTTP {e.status}: limite de requisições"
                                if self._rate_limited else f"HTTP {e.status}: {e.message}")
            self.notify(f"Erro API {'Arcus' if is_arcus else 'SoDEX'} ({acc['label']}): HTTP {e.status}",
                        severity="error")
        except aiohttp.ClientConnectorError:
            _api = "Arcus" if is_arcus else "SoDEX"
            self._last_error = f"Sem conexão com a {_api} API"
            self.notify(f"Sem conexão com a {_api} API ({acc['label']})", severity="error")
        except Exception as e:
            self._last_error = str(e)[:80]
            self.notify(f"Erro ({acc['label']}): {e}", severity="error")

    def _render_all(self) -> None:
        acc = ACCOUNTS[self._active_account]
        self.query_one("#header-bar", Static).update(self._build_header(self._last_update))
        self.query_one("#positions-panel",   PanelWidget).update(render_positions(self._positions))
        self.query_one("#pending-panel",     PanelWidget).update(render_pending_orders(self._orders))
        if acc.get("venue") == "arcus":
            self.query_one("#account-panel", PanelWidget).update(
                render_account(self._account, self._last_update,
                               label=f"sub {ARCUS_ACCOUNT_INDEX}", venue="Arcus", currency="USD")
            )
        else:
            self.query_one("#account-panel", PanelWidget).update(
                render_account(self._account, self._last_update, label=acc["label"])
            )
        self.query_one("#results-panel",     PanelWidget).update(render_results(self._results))

    def action_refresh(self) -> None:
        self.run_worker(self._do_refresh_once(), exclusive=False)
        self.notify("Atualizando dados...", timeout=1)

    def action_select_account(self, account_str: str) -> None:
        """Alterna qual API/wallet é exibida no dashboard (tecla [1], [2] ou [3] = Arcus)."""
        account_idx = int(account_str)
        if account_idx not in ACCOUNTS:
            return
        if account_idx == self._active_account:
            return
        self._active_account = account_idx
        # Reseta o throttle do histórico para buscar de imediato os dados
        # da conta recém-selecionada, em vez de reaproveitar o histórico
        # antigo da conta anterior.
        self._results_tick = 0
        self._results       = []
        self._results_loaded = False
        self._rate_limited   = False
        # Já troca a tabela de precisão de preço usada por _fmt_price()
        global _ACTIVE_VENUE
        _ACTIVE_VENUE = "arcus" if ACCOUNTS[account_idx].get("venue") == "arcus" else "sodex"
        self.notify(f"Exibindo {ACCOUNTS[account_idx]['label']}...", timeout=1)
        self.run_worker(self._do_refresh_once(), exclusive=False)

    def action_quit(self) -> None:
        self.exit()


if __name__ == "__main__":
    # Valida variáveis de ambiente antes de iniciar (Conta 1)
    missing = [
        k for k in (
            "SODEX_PUBLIC_KEY",
            "SODEX_PRIVATE_KEY",
            "SODEX_ACCOUNT_ID",
            "SODEX_WALLET_ADDRESS",
        )
        if not os.environ.get(k)
    ]
    if missing:
        print(f"❌ Variáveis ausentes no .env (Conta 1): {', '.join(missing)}")
        print("   Necessário: SODEX_PUBLIC_KEY, SODEX_PRIVATE_KEY, SODEX_ACCOUNT_ID, SODEX_WALLET_ADDRESS")
        exit(1)

    # Valida variáveis de ambiente da Conta 2 (segunda API/wallet)
    missing_2 = [
        k for k in (
            "SODEX_PUBLIC_KEY_CONTA_2",
            "SODEX_PRIVATE_KEY_CONTA_2",
            "SODEX_ACCOUNT_ID_CONTA_2",
            "SODEX_WALLET_ADDRESS_CONTA_2",
        )
        if not os.environ.get(k)
    ]
    if missing_2:
        print(f"❌ Variáveis ausentes no .env (Conta 2): {', '.join(missing_2)}")
        print("   Necessário: SODEX_PUBLIC_KEY_CONTA_2, SODEX_PRIVATE_KEY_CONTA_2, "
              "SODEX_ACCOUNT_ID_CONTA_2, SODEX_WALLET_ADDRESS_CONTA_2")
        exit(1)

    # Valida formato da chave privada de ambas as contas
    for _label, _pk in (("Conta 1", SODEX_PRIVATE_KEY), ("Conta 2", SODEX_PRIVATE_KEY_CONTA_2)):
        if not (_pk.startswith("0x") and len(_pk) == 66):
            print(f"❌ Chave privada inválida ({_label}): deve começar com '0x' e ter 66 caracteres (tem {len(_pk)})")
            exit(1)

    print(f"✓ Conectando à SoDEX Mainnet — {PERPS_ENDPOINT}")
    for _idx, _acc in ACCOUNTS.items():
        if _acc.get("venue") == "arcus":
            if ARCUS_CONFIG_ERRORS:
                print(f"  [{_acc['label']}]  ⚠ .env incompleto — tecla [3] não funcionará: "
                      f"{'; '.join(ARCUS_CONFIG_ERRORS)}")
            else:
                print(f"  [{_acc['label']}]  {ARCUS_REST_URL}  │  "
                      f"Subconta: {ARCUS_ACCOUNT_INDEX}  │  Wallet: {ARCUS_WALLET_ADDRESS}")
            continue
        print(f"  [{_acc['label']}]  API Key: {_acc['public_key']}  │  "
              f"Conta: {_acc['account_id']}  │  Wallet: {_acc['wallet']}")

    async def _connect_all_accounts() -> None:
        """Faz uma checagem inicial (GET /state) em cada conta para confirmar
        que ambas as APIs estão acessíveis antes de abrir o dashboard."""
        for _idx, _acc in ACCOUNTS.items():
            try:
                if _acc.get("venue") == "arcus":
                    await fetch_all_arcus()
                else:
                    await fetch_all(_acc["wallet"], _acc["account_id"])
                print(f"  ✓ {_acc['label']} conectada com sucesso.")
            except Exception as e:
                print(f"  ⚠ {_acc['label']}: falha ao conectar agora ({e}) — "
                      f"o dashboard tentará novamente ao selecioná-la.")

    asyncio.run(_connect_all_accounts())

    app = SoDEXDashboard()
    app.run()
