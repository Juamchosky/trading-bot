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
- `trend_filter_enabled`: habilita/deshabilita filtro de tendencia por SMA (default `False`).
- `trend_window`: ventana de la SMA de tendencia (default `50`).
- `trend_slope_filter_enabled`: habilita/deshabilita filtro de pendiente de tendencia (default `False`).
- `trend_slope_lookback`: velas hacia atras para comparar la pendiente de la SMA de tendencia (default `3`).
- `volatility_filter_enabled`: habilita/deshabilita filtro de volatilidad para compras (default `False`).
- `volatility_window`: cantidad de velas recientes usadas para volatilidad promedio (default `20`).
- `min_volatility_pct`: volatilidad minima promedio (%) para permitir compras (default `0.30`).
- `regime_filter_enabled`: habilita/deshabilita filtro de regimen para compras (default `False`).
- `regime_window`: cantidad de cierres recientes usados para calcular volatilidad de retornos (default `50`).
- `min_regime_volatility_pct`: volatilidad minima (%) de retornos para permitir compras (default `0.30`).
- `signal_confirmation_bars`: cantidad de velas que el cruce SMA corto>SMA largo debe mantenerse antes de comprar (default `0`).
- `warmup_bars`: cantidad de velas iniciales a ignorar antes de habilitar señales (default `0`).
- `momentum_filter_enabled`: habilita/deshabilita filtro de momentum RSI para compras (default `False`).
- `momentum_window`: cantidad de cierres usados para calcular RSI simple (default `14`).
- `min_momentum_rsi`: RSI minimo requerido para permitir compras cuando el filtro esta activo (default `55.0`).
- `breakout_filter_enabled`: habilita/deshabilita filtro de breakout por estructura de precio (default `False`).
- `breakout_lookback`: cantidad de cierres previos usados para confirmar ruptura del maximo/minimo (default `5`).
- `max_drawdown_limit_pct`: limite de drawdown maximo (%) para activar kill-switch en backtest. Si es `None`, no aplica.

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
- kill-switch por drawdown: si `max_drawdown_limit_pct` se alcanza/supera, se bloquean solo nuevas entradas `buy`; los cierres (`signal`, `stop_loss`, `take_profit`, `forced_close`) siguen igual.

Filtro de volatilidad (simple):

- se calcula como promedio del retorno porcentual absoluto entre cierres consecutivos en las ultimas `volatility_window` velas.
- si `volatility_filter_enabled=True` y esa volatilidad promedio es menor a `min_volatility_pct`, se bloquea la seÃ±al `buy`.
- las seÃ±ales `sell` no se bloquean con este filtro.

Filtro de regimen (volatilidad de retornos):

- toma los ultimos `regime_window` cierres.
- calcula retornos porcentuales simples entre cierres consecutivos.
- calcula la desviacion estandar poblacional de esos retornos y la expresa en `%`.
- si `regime_filter_enabled=True` y esa volatilidad es menor a `min_regime_volatility_pct`, se bloquea `buy`.
- las señales `sell` no se retrasan ni se bloquean con este filtro.

Filtro de pendiente de tendencia (simple):

- calcula la SMA larga actual de la estrategia (`long_window`).
- calcula esa SMA larga de hace `trend_slope_lookback` velas.
- si `trend_slope_filter_enabled=True` y `SMA_larga_actual <= SMA_larga_pasada`, se bloquea `buy`.
- si `trend_slope_filter_enabled=False`, se mantiene la logica actual.

Confirmacion de senal:

- si `signal_confirmation_bars > 0`, la compra solo se habilita si el cruce `SMA_corta > SMA_larga` ya estaba presente durante esa cantidad de velas previas.
- las ventas no esperan confirmacion adicional para no retrasar la salida.

Warmup:

- si `warmup_bars > 0`, la estrategia devuelve `hold` durante las primeras `warmup_bars` velas.

Filtro de momentum RSI (simple):

- usa RSI clasico simple sobre los ultimos `momentum_window` cambios de cierre.
- si `momentum_filter_enabled=True` y no hay suficientes datos, se bloquea `buy` (`hold`).
- si `momentum_filter_enabled=True` y `RSI < min_momentum_rsi`, se bloquea `buy`.
- las señales `sell` no se bloquean con este filtro.

Filtro de breakout por estructura:

- mantiene el SMA cross como condicion base; no reemplaza la logica de cruce.
- si `breakout_filter_enabled=True`, una compra solo se habilita si el `close` actual es mayor que el maximo de los ultimos `breakout_lookback` cierres previos.
- si `breakout_filter_enabled=True`, una venta solo se habilita si el `close` actual es menor que el minimo de los ultimos `breakout_lookback` cierres previos.
- si no hay suficientes cierres para evaluar la ruptura, la estrategia devuelve `hold`.

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
- `backtest_summary.csv`: resumen agregado por corrida, en modo append, una fila nueva por ejecucion, incluyendo metricas y parametros usados (`short_window`, `long_window`, `trend_filter_enabled`, `trend_window`, `trend_slope_filter_enabled`, `trend_slope_lookback`, `volatility_filter_enabled`, `volatility_window`, `min_volatility_pct`, `regime_filter_enabled`, `regime_window`, `min_regime_volatility_pct`, `signal_confirmation_bars`, `warmup_bars`, `momentum_filter_enabled`, `momentum_window`, `min_momentum_rsi`, `breakout_filter_enabled`, `breakout_lookback`, `stop_loss_pct`, `take_profit_pct`, `max_drawdown_limit_pct`, `position_size_pct`, `fee_rate`, `max_drawdown_pct`).
- `equity_curve.csv`: curva de equity de la ultima corrida (`timestamp`, `equity`), sobrescrito en cada nueva ejecucion.

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
- `max_drawdown_pct`: peor drawdown porcentual observado durante la corrida.

Si no hay trades cerrados, estas metricas devuelven `0` para evitar divisiones por cero.

