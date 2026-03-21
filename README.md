# Trading Bot (Simulacion)

Estructura inicial funcional de un bot de trading en modo simulacion (paper trading).

## Estructura

- `main.py`: punto de entrada.
- `bot/config.py`: parametros de simulacion.
- `bot/market/simulator.py`: generacion de precios simulados.
- `bot/strategy/sma_cross.py`: estrategia de cruce de medias moviles.
- `bot/execution/paper_broker.py`: ejecucion simulada (sin ordenes reales).
- `bot/execution/binance_executor.py`: ejecucion para Binance Spot Testnet con controles de seguridad.
- `bot/engine.py`: loop principal de trading y metricas.

## Ejecutar

```bash
python main.py
```

## Configuracion

En `SimulationConfig` podes ajustar `fee_rate` (comision por operacion).
- Valor por defecto: `0.001` (0.1%).
- Se aplica en compras y ventas del paper broker.

## Binance Spot Testnet (seguro por defecto)

El executor de Binance usa por defecto `https://testnet.binance.vision` y requiere variables de entorno:

```bash
export BINANCE_API_KEY="tu_api_key"
export BINANCE_API_SECRET="tu_api_secret"
```

En PowerShell:

```powershell
$env:BINANCE_API_KEY="tu_api_key"
$env:BINANCE_API_SECRET="tu_api_secret"
```

Controles incluidos:
- `live_trading_enabled=False` por defecto, por lo tanto no permite ordenes reales.
- `test_order()` usa `/api/v3/order/test` para validar ordenes sin ejecucion real.
- validacion de simbolos permitidos (`allowed_symbols`).
- limite de tamano por orden (`max_order_size`).

Ejemplo rapido:

```python
from bot.execution.binance_executor import BinanceExecutor, BinanceOrderRequest

executor = BinanceExecutor(
    live_trading_enabled=False,
    allowed_symbols=("BTCUSDT", "ETHUSDT"),
    max_order_size=0.01,
)

executor.test_order(
    BinanceOrderRequest(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity="0.001",
    )
)
```

## Resultado esperado

Imprime:
- balance inicial/final
- retorno porcentual
- cantidad de operaciones
- win rate
