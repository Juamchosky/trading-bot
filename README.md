# Trading Bot (Simulacion + Binance Spot Testnet)

Estructura inicial funcional de un bot de trading con seleccion de modo de ejecucion.

## Estructura

- `main.py`: punto de entrada.
- `bot/config.py`: parametros de simulacion y modo de ejecucion.
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

En `SimulationConfig` podes ajustar:

- `execution_mode`: `"paper"` (default) o `"binance_testnet"`.
- `fee_rate`: comision por operacion (default `0.001`).
- `binance_test_order_qty`: cantidad usada en test order de Binance (default `"0.001"`).

Comportamiento por modo:

- `paper`: usa solo `PaperBroker` (simulacion pura).
- `binance_testnet`: mantiene el `PaperBroker` para metricas y, con la misma decision de la estrategia (`buy/sell`), envia `test_order()` a Binance Spot Testnet.

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

- no se usa `place_order()` desde el engine.
- solo se usa `test_order()` (`/api/v3/order/test`).
- `live_trading_enabled=False` forzado en el engine para modo `binance_testnet`.
- validacion de simbolos permitidos (`allowed_symbols`).
- limite de tamano por orden (`max_order_size`).

## Resultado esperado

Imprime:

- balance inicial/final
- retorno porcentual
- cantidad de operaciones
- win rate
