# ⚙️ Configuração de Variáveis de Ambiente (`.env`)

Crie um arquivo `.env` na raiz do seu projeto e adicione as variáveis de ambiente abaixo ajustando conforme a sua necessidade.

```env
# ==========================================
# ARCUS CONFIGURATION
# ==========================================

# Ambiente
ARCUS_ENV=Mainnet
ARCUS_REST_URL=https://api.arcus.xyz
ARCUS_WS_URL=wss://api.arcus.xyz/v1/ws

# Credenciais (SECRETAS)
# Chave privada Ed25519 em hex ("API Signing Key"), mostrada uma única vez no Web App
ARCUS_API_SIGNING_KEY=your_arcus_signing_key_here

# Conta
# Endereço da carteira (master) que autorizou a chave de API
ARCUS_WALLET_ADDRESS=your_wallet_address_here
# Número da subconta escolhido ao autorizar a chave (padrão 0)
ARCUS_ACCOUNT_INDEX=0

# Mercado
ARCUS_MARKET_ID=1 # 1 = BTC-USD

# Risco
ORDER_SIZE=0.001
MAX_POSITION_SIZE=0.01
MAX_DAILY_LOSS_USD=50
MAX_OPEN_ORDERS=10
MAX_SLIPPAGE_PCT=1
ORDER_TTL_DAYS=30

# Operação
LOG_LEVEL=INFO
DRY_RUN=true


# ==========================================
# SODEX CONFIGURATION
# ==========================================

# SODEX CONTA 1
SODEX_PUBLIC_KEY=sua_api_key_sodex_1
SODEX_PRIVATE_KEY=sua_private_key_sodex_1
SODEX_ACCOUNT_ID=seu_account_id_sodex_1
SODEX_WALLET_ADDRESS=seu_wallet_address_sodex_1

# SODEX CONTA 2
SODEX_PUBLIC_KEY_CONTA_2=sua_api_key_sodex_2
SODEX_PRIVATE_KEY_CONTA_2=sua_private_key_sodex_2
SODEX_ACCOUNT_ID_CONTA_2=seu_account_id_sodex_2
SODEX_WALLET_ADDRESS_CONTA_2=seu_wallet_address_sodex_2
```

## 📋 Descrição dos Parâmetros

### Arcus Protocol
| Variável | Descrição | Valor Padrão / Exemplo |
| :--- | :--- | :--- |
| `ARCUS_ENV` | Rede de execução | `Mainnet` |
| `ARCUS_REST_URL` | URL base da API REST | `https://api.arcus.xyz` |
| `ARCUS_WS_URL` | URL base do WebSocket | `wss://api.arcus.xyz/v1/ws` |
| `ARCUS_API_SIGNING_KEY` | Chave privada Ed25519 em hex (API Signing Key) | *Segredo* |
| `ARCUS_WALLET_ADDRESS` | Endereço da carteira master | `0x...` |
| `ARCUS_ACCOUNT_INDEX` | Índice da subconta | `0` |
| `ARCUS_MARKET_ID` | Identificador do mercado (ex: 1 = BTC-USD) | `1` |

### Gestão de Risco e Operação
| Variável | Descrição |
| :--- | :--- |
| `ORDER_SIZE` | Tamanho padrão de cada ordem |
| `MAX_POSITION_SIZE` | Tamanho máximo permitido para a posição |
| `MAX_DAILY_LOSS_USD` | Perda diária máxima permitida (USD) |
| `MAX_OPEN_ORDERS` | Limite de ordens abertas simultaneamente |
| `MAX_SLIPPAGE_PCT` | Slippage máximo permitido (%) |
| `ORDER_TTL_DAYS` | Tempo de vida da ordem em dias (Time To Live) |
| `LOG_LEVEL` | Nível de detalhar do log (`DEBUG`, `INFO`, `WARN`, `ERROR`) |
| `DRY_RUN` | Se `true`, executa simulações sem enviar ordens reais |

### Sodex Exchange
| Variável | Descrição |
| :--- | :--- |
| `SODEX_PUBLIC_KEY` | Nome/Chave pública da API Sodex |
| `SODEX_PRIVATE_KEY` | Chave privada gerada na API Sodex |
| `SODEX_ACCOUNT_ID` | ID da conta Sodex |
| `SODEX_WALLET_ADDRESS` | Endereço da carteira conectada à Sodex |
