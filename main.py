from bot.config import SimulationConfig
from bot.engine import run_simulation


def main() -> None:
    config = SimulationConfig(
        execution_mode="binance_testnet"  # 👈 ACTIVAMOS BINANCE TESTNET
    )

    result = run_simulation(config)

    print(f"Bot de trading iniciado (modo {config.execution_mode})")
    print(f"Balance inicial: {result.initial_balance:.2f}")
    print(f"Balance final:   {result.final_balance:.2f}")
    print(f"Retorno:         {result.return_pct:.2f}%")
    print(f"Operaciones:     {result.total_trades}")
    print(f"Win rate:        {result.win_rate_pct:.2f}%")


if __name__ == "__main__":
    main()
