# Trading Bot (Simulacion)

Estructura inicial funcional de un bot de trading en modo simulacion (paper trading).

## Estructura

- `main.py`: punto de entrada.
- `bot/config.py`: parametros de simulacion.
- `bot/market/simulator.py`: generacion de precios simulados.
- `bot/strategy/sma_cross.py`: estrategia de cruce de medias moviles.
- `bot/execution/paper_broker.py`: ejecucion simulada (sin ordenes reales).
- `bot/engine.py`: loop principal de trading y metricas.

## Ejecutar

```bash
python main.py
```

## Configuracion

En `SimulationConfig` podes ajustar `fee_rate` (comision por operacion).
- Valor por defecto: `0.001` (0.1%).
- Se aplica en compras y ventas del paper broker.

## Resultado esperado

Imprime:
- balance inicial/final
- retorno porcentual
- cantidad de operaciones
- win rate
