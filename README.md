# Trading Bot (Simulacion + Binance Spot Testnet)

Estructura inicial funcional de un bot de trading con seleccion de modo de ejecucion.

## Estructura

- `main.py`: punto de entrada.
- `bot/config.py`: parametros de simulacion y modo de ejecucion.
- `bot/market/simulator.py`: generacion sintetica de velas OHLCV simuladas.
- `bot/market/binance_data.py`: descarga de velas OHLCV historicas publicas de Binance Spot.
- `bot/strategy/sma_cross.py`: estrategia de cruce de medias moviles.
- `bot/execution/paper_broker.py`: ejecucion simulada (sin ordenes reales).
- `bot/execution/binance_executor.py`: ejecucion para Binance Spot Testnet con controles de seguridad.
- `bot/engine.py`: loop principal de trading y metricas.

## Ejecutar

```bash
python main.py
```

Para correr multiples combinaciones de parametros y agregar una fila por corrida en `backtest_summary.csv`:

```bash
python sweep_backtest.py
```

Opciones utiles:

- `python sweep_backtest.py --market-data-mode simulated`
- `python sweep_backtest.py --max-runs 5`

## Configuracion

En `SimulationConfig` podes ajustar:

- `execution_mode`: `"paper"` (default) o `"binance_testnet"`.
- `market_data_mode`: `"simulated"` (default) o `"binance_historical"`.
- `fee_rate`: comision por operacion (default `0.001`).
- `binance_test_order_qty`: cantidad usada en test order de Binance (default `"0.001"`).
- `binance_interval`: intervalo de velas de Binance (default `"1h"`).
- `candle_count`: cantidad de velas para simulacion o backtest historico.

Comportamiento por modo:

- `paper`: usa solo `PaperBroker` (simulacion pura).
- `binance_testnet`: mantiene el `PaperBroker` para metricas y, con la misma decision de la estrategia (`buy/sell`), envia `test_order()` a Binance Spot Testnet.

Comportamiento por fuente de mercado:

- `simulated`: usa velas OHLCV sinteticas (`bot/market/simulator.py`).
- `binance_historical`: usa velas OHLCV reales de Binance Spot (`GET /api/v3/klines`, sin API key).

Fidelidad de ejecucion en backtest:

- señales de estrategia: se calculan con `close`.
- stop loss: se evalua con `low` (intra-vela).
- take profit: se evalua con `high` (intra-vela).

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

- modo
- balance inicial/final
- retorno porcentual
- cantidad de operaciones
- win rate
- closed trades
- avg pnl
- best trade pnl
- worst trade pnl
- profit factor (`inf` si corresponde)
- avg win pnl
- avg loss pnl

Tambien genera archivos CSV en la raiz del proyecto:

- `backtest_trades.csv`: detalle de trades cerrados de la ultima corrida.
- `backtest_summary.csv`: resumen agregado por corrida, en modo append, una fila nueva por ejecucion, incluyendo metricas y parametros usados (`short_window`, `long_window`, `stop_loss_pct`, `take_profit_pct`, `position_size_pct`, `fee_rate`).

Ademas, `run_simulation()` ahora devuelve en `SimulationResult.trades` el detalle de cada trade cerrado del backtest, incluyendo:

- `entry_timestamp`
- `exit_timestamp`
- `side`
- `entry_price`
- `exit_price`
- `quantity`
- `pnl`
- `exit_reason` (`signal`, `stop_loss`, `take_profit`, `forced_close`)

Tambien incluye metricas agregadas basadas en trades cerrados:

- `closed_trades`: cantidad de trades cerrados.
- `avg_pnl`: PnL promedio por trade cerrado.
- `best_trade_pnl`: mejor PnL entre trades cerrados.
- `worst_trade_pnl`: peor PnL entre trades cerrados.
- `profit_factor`: `gross_profit / abs(gross_loss)`; si no hay perdidas, devuelve `inf` (o `0.0` si tampoco hay ganancias).
- `avg_win_pnl`: promedio de PnL de trades ganadores.
- `avg_loss_pnl`: promedio de PnL de trades perdedores.

Si no hay trades cerrados, estas metricas devuelven `0` para evitar divisiones por cero.
