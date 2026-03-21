from dataclasses import dataclass

from bot.models import Trade


@dataclass
class PaperBroker:
    cash: float
    fee_rate: float = 0.001
    position_qty: float = 0.0
    entry_price: float = 0.0

    def buy_all(self, price: float) -> Trade | None:
        if self.position_qty > 0.0 or self.cash <= 0.0:
            return None
        qty = self.cash / (price * (1.0 + self.fee_rate))
        self.position_qty = qty
        self.entry_price = price
        self.cash = 0.0
        return Trade(side="buy", price=price, quantity=qty)

    def sell_all(self, price: float) -> Trade | None:
        if self.position_qty <= 0.0:
            return None
        qty = self.position_qty
        gross_proceeds = qty * price
        sell_fee = gross_proceeds * self.fee_rate
        proceeds = gross_proceeds - sell_fee
        buy_cost = qty * self.entry_price
        buy_fee = buy_cost * self.fee_rate
        pnl = proceeds - (buy_cost + buy_fee)
        self.cash = proceeds
        self.position_qty = 0.0
        self.entry_price = 0.0
        return Trade(side="sell", price=price, quantity=qty, pnl=pnl)

    def equity(self, mark_price: float) -> float:
        return self.cash + (self.position_qty * mark_price)
