from bot.execution.binance_executor import BinanceExecutor, BinanceOrderRequest

executor = BinanceExecutor(
    base_url="https://api.binance.com",
    live_trading_enabled=False,
    allowed_symbols=("BTCUSDT",),
    max_order_size=0.01,
)

response = executor.test_order(
    BinanceOrderRequest(
        symbol="BTCUSDT",
        side="BUY",
        quantity="0.001",
    )
)

print("Test order OK:", response)