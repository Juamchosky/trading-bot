import math

from bot.config import SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult


def _format_profit_factor(profit_factor: float) -> str:
    if math.isinf(profit_factor):
        return "inf"
    return f"{profit_factor:.2f}"


def _print_simulation_summary(config: SimulationConfig, result: SimulationResult) -> None:
    print(f"Bot de trading iniciado (modo {config.execution_mode})")
    print(f"Balance inicial: {result.initial_balance:.2f}")
    print(f"Balance final:   {result.final_balance:.2f}")
    print(f"Retorno:         {result.return_pct:.2f}%")
    print(f"Operaciones:     {result.total_trades}")
    print(f"Win rate:        {result.win_rate_pct:.2f}%")
    print(f"Closed trades:   {result.closed_trades}")
    print(f"Avg PnL:         {result.avg_pnl:.2f}")
    print(f"Best trade PnL:  {result.best_trade_pnl:.2f}")
    print(f"Worst trade PnL: {result.worst_trade_pnl:.2f}")
    print(f"Profit factor:   {_format_profit_factor(result.profit_factor)}")
    print(f"Avg win PnL:     {result.avg_win_pnl:.2f}")
    print(f"Avg loss PnL:    {result.avg_loss_pnl:.2f}")


def main() -> None:
    config = SimulationConfig(
        execution_mode="binance_testnet"  # 👈 ACTIVAMOS BINANCE TESTNET
    )

    result = run_simulation(config)
    _print_simulation_summary(config, result)


if __name__ == "__main__":
    main()
