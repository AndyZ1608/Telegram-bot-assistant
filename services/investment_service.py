"""
Investment service for watchlist, alerts, and simple portfolio tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.db import get_session
from database.models import Portfolio, PriceAlert, Watchlist
from services.market_data import get_stock_provider


class InvestmentError(Exception):
    """Base investment service error."""


class DuplicateSymbolError(InvestmentError):
    """Raised when adding a duplicate watchlist symbol."""


class SymbolNotFoundError(InvestmentError):
    """Raised when the market provider has no data for a symbol."""


class WatchlistNotFoundError(InvestmentError):
    """Raised when a watchlist symbol does not exist for a user."""


class AlertNotFoundError(InvestmentError):
    """Raised when an alert does not exist for a user."""


class PortfolioNotFoundError(InvestmentError):
    """Raised when a portfolio row does not exist for a user."""


class InvalidConditionError(InvestmentError):
    """Raised when an alert condition is not supported."""


@dataclass(frozen=True)
class WatchlistQuote:
    symbol: str
    market: str | None
    price: float | None
    change: float | None
    change_percent: float | None
    updated_at: str | None
    source: str | None
    error: str | None = None


@dataclass(frozen=True)
class AlertCheckResult:
    id: int
    symbol: str
    condition_type: str
    target_price: float
    current_price: float | None
    triggered: bool
    error: str | None = None


@dataclass(frozen=True)
class PortfolioView:
    id: int
    symbol: str
    quantity: float
    buy_price: float
    cost_value: float
    current_price: float | None
    market_value: float | None
    pnl: float | None
    pnl_percent: float | None
    source: str | None
    error: str | None = None


async def add_watch_symbol(user_id: int, symbol: str) -> Watchlist:
    symbol = symbol.upper()
    quote = await get_stock_provider().get_stock_price(symbol)
    if not quote:
        raise SymbolNotFoundError(f"{symbol} not found in provider.")

    async with get_session() as session:
        existing = await session.scalar(
            select(Watchlist.id).where(
                Watchlist.user_id == user_id,
                Watchlist.symbol == symbol,
            )
        )
        if existing is not None:
            raise DuplicateSymbolError(f"{symbol} already exists in watchlist.")

        watch = Watchlist(
            user_id=user_id,
            symbol=symbol,
            market=(quote or {}).get("market"),
        )
        session.add(watch)
        return watch


async def remove_watch_symbol(user_id: int, symbol: str) -> None:
    symbol = symbol.upper()
    async with get_session() as session:
        result = await session.execute(
            select(Watchlist).where(
                Watchlist.user_id == user_id,
                Watchlist.symbol == symbol,
            )
        )
        watch = result.scalar_one_or_none()
        if watch is None:
            raise WatchlistNotFoundError(f"{symbol} not found in watchlist.")
        await session.delete(watch)


async def list_watch_symbols(user_id: int) -> list[str]:
    async with get_session() as session:
        result = await session.execute(
            select(Watchlist.symbol)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.symbol)
        )
        return list(result.scalars().all())


async def list_watch_quotes(user_id: int) -> list[WatchlistQuote]:
    symbols = await list_watch_symbols(user_id)
    provider = get_stock_provider()
    quotes: list[WatchlistQuote] = []
    for symbol in symbols:
        try:
            data = await provider.get_stock_price(symbol)
            if not data:
                quotes.append(WatchlistQuote(symbol, None, None, None, None, None, None, "no data"))
                continue
            quotes.append(_quote_from_data(symbol, data))
        except Exception as exc:
            quotes.append(WatchlistQuote(symbol, None, None, None, None, None, None, str(exc)))
    return quotes


def _quote_from_data(symbol: str, data: dict[str, Any]) -> WatchlistQuote:
    return WatchlistQuote(
        symbol=data.get("symbol", symbol),
        market=data.get("market"),
        price=float(data["price"]) if data.get("price") is not None else None,
        change=float(data["change"]) if data.get("change") is not None else None,
        change_percent=float(data["change_percent"]) if data.get("change_percent") is not None else None,
        updated_at=data.get("updated_at"),
        source=data.get("source"),
    )


async def add_price_alert(user_id: int, symbol: str, condition_type: str, target_price: float) -> PriceAlert:
    condition_type = condition_type.lower()
    if condition_type not in {"above", "below"}:
        raise InvalidConditionError("condition must be above or below.")
    symbol = symbol.upper()
    quote = await get_stock_provider().get_stock_price(symbol)
    if not quote:
        raise SymbolNotFoundError(f"{symbol} not found in provider.")

    async with get_session() as session:
        alert = PriceAlert(
            user_id=user_id,
            symbol=symbol,
            condition_type=condition_type,
            target_price=target_price,
            is_active=True,
        )
        session.add(alert)
        return alert


async def list_price_alerts(user_id: int) -> list[PriceAlert]:
    async with get_session() as session:
        result = await session.execute(
            select(PriceAlert)
            .where(PriceAlert.user_id == user_id)
            .order_by(PriceAlert.is_active.desc(), PriceAlert.id)
        )
        return list(result.scalars().all())


async def delete_price_alert(user_id: int, alert_id: int) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(PriceAlert).where(
                PriceAlert.user_id == user_id,
                PriceAlert.id == alert_id,
            )
        )
        alert = result.scalar_one_or_none()
        if alert is None:
            raise AlertNotFoundError(f"Alert #{alert_id} not found.")
        await session.delete(alert)


async def check_price_alerts(user_id: int) -> list[AlertCheckResult]:
    alerts = [alert for alert in await list_price_alerts(user_id) if alert.is_active]
    provider = get_stock_provider()
    results: list[AlertCheckResult] = []
    async with get_session() as session:
        for alert in alerts:
            try:
                data = await provider.get_stock_price(alert.symbol)
                if not data or data.get("price") is None:
                    results.append(_alert_result(alert, None, False, "no data"))
                    continue
                current_price = float(data["price"])
                triggered = (
                    current_price >= alert.target_price
                    if alert.condition_type == "above"
                    else current_price <= alert.target_price
                )
                if triggered:
                    db_alert = await session.get(PriceAlert, alert.id)
                    if db_alert is not None:
                        db_alert.triggered_at = datetime.utcnow()
                        db_alert.is_active = False
                results.append(_alert_result(alert, current_price, triggered))
            except Exception as exc:
                results.append(_alert_result(alert, None, False, str(exc)))
    return results


def _alert_result(
    alert: PriceAlert,
    current_price: float | None,
    triggered: bool,
    error: str | None = None,
) -> AlertCheckResult:
    return AlertCheckResult(
        id=alert.id,
        symbol=alert.symbol,
        condition_type=alert.condition_type,
        target_price=float(alert.target_price),
        current_price=current_price,
        triggered=triggered,
        error=error,
    )


async def add_portfolio_position(
    user_id: int,
    symbol: str,
    quantity: float,
    buy_price: float,
) -> Portfolio:
    symbol = symbol.upper()
    quote = await get_stock_provider().get_stock_price(symbol)
    if not quote:
        raise SymbolNotFoundError(f"{symbol} not found in provider.")

    async with get_session() as session:
        position = Portfolio(
            user_id=user_id,
            symbol=symbol,
            quantity=quantity,
            buy_price=buy_price,
        )
        session.add(position)
        return position


async def remove_portfolio_position(user_id: int, portfolio_id: int) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Portfolio).where(
                Portfolio.user_id == user_id,
                Portfolio.id == portfolio_id,
            )
        )
        position = result.scalar_one_or_none()
        if position is None:
            raise PortfolioNotFoundError(f"Portfolio #{portfolio_id} not found.")
        await session.delete(position)


async def list_portfolio(user_id: int) -> list[PortfolioView]:
    async with get_session() as session:
        result = await session.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .order_by(Portfolio.id)
        )
        positions = list(result.scalars().all())

    provider = get_stock_provider()
    rows: list[PortfolioView] = []
    for position in positions:
        cost_value = float(position.quantity) * float(position.buy_price)
        try:
            data = await provider.get_stock_price(position.symbol)
            if not data or data.get("price") is None:
                rows.append(_portfolio_view(position, cost_value, None, None, None, None, "no data"))
                continue
            current_price = float(data["price"])
            market_value = float(position.quantity) * current_price
            pnl = market_value - cost_value
            pnl_percent = pnl / cost_value if cost_value else 0.0
            rows.append(
                _portfolio_view(
                    position,
                    cost_value,
                    current_price,
                    market_value,
                    pnl,
                    pnl_percent,
                    None,
                    data.get("source"),
                )
            )
        except Exception as exc:
            rows.append(_portfolio_view(position, cost_value, None, None, None, None, str(exc)))
    return rows


def _portfolio_view(
    position: Portfolio,
    cost_value: float,
    current_price: float | None,
    market_value: float | None,
    pnl: float | None,
    pnl_percent: float | None,
    error: str | None = None,
    source: str | None = None,
) -> PortfolioView:
    return PortfolioView(
        id=position.id,
        symbol=position.symbol,
        quantity=float(position.quantity),
        buy_price=float(position.buy_price),
        cost_value=cost_value,
        current_price=current_price,
        market_value=market_value,
        pnl=pnl,
        pnl_percent=pnl_percent,
        source=source,
        error=error,
    )
