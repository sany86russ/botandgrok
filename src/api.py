import asyncio
import logging
import ccxt.async_support as ccxt
from typing import Dict, List, Any, Callable
from src.utils import float_safe

log = logging.getLogger("api")

class BingXAPI:
    def __init__(self, cfg: Dict):
        self.exchange = ccxt.bingx({
            'apiKey': cfg.get("api", {}).get("bingx", {}).get("api_key"),
            'secret': cfg.get("api", {}).get("bingx", {}).get("secret"),
            'enableRateLimit': True,
        })
        self.max_retries = cfg.get("network", {}).get("max_retries", 3)
        self.backoff_base_ms = cfg.get("network", {}).get("backoff_base_ms", 250)

    async def fetch_with_retry(self, method, *args, **kwargs) -> Any:
        for attempt in range(self.max_retries):
            try:
                return await method(*args, **kwargs)
            except Exception as e:
                log.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt == self.max_retries - 1:
                    log.error(f"Failed after {self.max_retries} attempts: {e}")
                    return None
                await asyncio.sleep(self.backoff_base_ms / 1000 * (2 ** attempt))
        return None

    async def fetch_klines(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        data = await self.fetch_with_retry(self.exchange.fetch_ohlcv, symbol, interval, limit=limit)
        if not data:
            log.error(f"Failed to fetch klines for {symbol}")
            return []
        return data

    async def fetch_oi_hist(self, symbol: str, period: str = "15m", limit: int = 500) -> List[Dict[str, Any]]:
        data = await self.fetch_with_retry(self.exchange.fetch_open_interest_history, symbol, period, limit=limit)
        if not data:
            log.error(f"Failed to fetch OI history for {symbol}")
            return []
        return data

    async def fetch_spot_price(self, symbol: str) -> float:
        ticker = await self.fetch_with_retry(self.exchange.fetch_ticker, symbol)
        if not ticker:
            log.error(f"Failed to fetch spot price for {symbol}")
            return 0.0
        return float_safe(ticker.get("last", 0.0))

    def subscribe_book_ticker(self, symbol: str, callback: Callable):
        try:
            self.exchange.load_markets()
            self.exchange.ws.on('ticker', callback, symbol)
        except Exception:
            log.exception(f"WebSocket failed for {symbol}")

class BinanceAPI:
    def __init__(self, cfg: Dict):
        self.exchange = ccxt.binance({
            'apiKey': cfg.get("api", {}).get("binance", {}).get("api_key", ""),
            'secret': cfg.get("api", {}).get("binance", {}).get("secret", ""),
            'enableRateLimit': True,
        })
        self.max_retries = cfg.get("network", {}).get("max_retries", 3)
        self.backoff_base_ms = cfg.get("network", {}).get("backoff_base_ms", 250)

    async def fetch_with_retry(self, method, *args, **kwargs) -> Any:
        for attempt in range(self.max_retries):
            try:
                return await method(*args, **kwargs)
            except Exception as e:
                log.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt == self.max_retries - 1:
                    log.error(f"Failed after {self.max_retries} attempts: {e}")
                    return None
                await asyncio.sleep(self.backoff_base_ms / 1000 * (2 ** attempt))
        return None

    async def fetch_klines(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        data = await self.fetch_with_retry(self.exchange.fetch_ohlcv, symbol, interval, limit=limit)
        if not data:
            log.error(f"Failed to fetch klines for {symbol}")
            return []
        return data

    async def fetch_oi_hist(self, symbol: str, period: str = "15m", limit: int = 500) -> List[Dict[str, Any]]:
        data = await self.fetch_with_retry(self.exchange.fetch_open_interest_history, symbol, period, limit=limit)
        if not data:
            log.error(f"Failed to fetch OI history for {symbol}")
            return []
        return data

    async def fetch_spot_price(self, symbol: str) -> float:
        ticker = await self.fetch_with_retry(self.exchange.fetch_ticker, symbol)
        if not ticker:
            log.error(f"Failed to fetch spot price for {symbol}")
            return 0.0
        return float_safe(ticker.get("last", 0.0))

    def subscribe_book_ticker(self, symbol: str, callback: Callable):
        try:
            self.exchange.load_markets()
            self.exchange.ws.on('ticker', callback, symbol)
        except Exception:
            log.exception(f"WebSocket failed for {symbol}")