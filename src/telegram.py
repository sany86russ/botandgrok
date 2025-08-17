import logging
import httpx
from typing import Dict, Any
import asyncio

log = logging.getLogger("telegram")

async def send_tg(cfg: Dict, message: str):
    bot_token = cfg.get("telegram", {}).get("bot_token")
    chat_id = cfg.get("telegram", {}).get("chat_id")
    if not bot_token or not chat_id:
        log.warning("Telegram bot_token or chat_id missing")
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message}
            )
        except Exception as e:
            log.error(f"Failed to send Telegram message: {e}")

async def send_signal(cfg: Dict, payload: Dict[str, Any]):
    bot_token = cfg.get("telegram", {}).get("bot_token")
    chat_id = cfg.get("telegram", {}).get("chat_id")
    if not bot_token or not chat_id:
        log.warning("Telegram bot_token or chat_id missing")
        return
    message = (
        f"📊 Новый сигнал [{payload['strategy_type']}]\n"
        f"Символ: {payload['symbol']}\n"
        f"Сторона: {payload['side'].upper()}\n"
        f"Цена входа: {payload['entry']:.6f} USDT\n"
        f"Тейк-профит 1: {payload['tp1']:.6f} USDT\n"
        f"Стоп-лосс: {payload['sl']:.6f} USDT\n"
        f"Леверидж: {payload['leverage']}x\n"
        f"Score: {payload['score']:.2f}\n"
        f"Причины: {', '.join(payload.get('reasons', []))}\n"
        f"ATR%: {payload['atr_pct']:.2f}%\n"
        f"ADX: {payload['adx']:.2f}\n"
        f"Корреляция с BTC: {payload['corr_btc']:.2f}"
    )
    if payload['strategy_type'] in ["SWING", "POSITION"]:
        message += f"\nOBV: {payload.get('obv', 0):.2f}"
        message += f"\nIchimoku: {payload.get('ichimoku', 'N/A')}"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message}
            )
        except Exception as e:
            log.error(f"Failed to send Telegram signal: {e}")

async def command_loop(cfg: Dict):
    bot_token = cfg.get("telegram", {}).get("bot_token")
    chat_id = cfg.get("telegram", {}).get("chat_id")
    if not bot_token or not chat_id:
        log.warning("Telegram bot_token or chat_id missing")
        return
    last_update_id = 0
    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={"offset": last_update_id + 1, "timeout": 30}
                )
                updates = resp.json().get("result", [])
                for update in updates:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        if text == "/start":
                            await send_tg(cfg, "Бот запущен! Отправляю торговые сигналы.")
                        elif text == "/status":
                            performance = analyze_recent_performance(cfg, days=7)
                            msg = "📊 Статус стратегий (7 дней):\n"
                            for strat, metrics in performance.items():
                                msg += (
                                    f"{strat}:\n"
                                    f"Сигналов: {metrics['n']}\n"
                                    f"Win Rate: {metrics['win_rate']:.2%}\n"
                                    f"Средний R: {metrics['avg_R']:.2f}\n"
                                    f"Макс. R: {metrics['max_R']:.2f}\n"
                                    f"Мин. R: {metrics['min_R']:.2f}\n\n"
                                )
                            await send_tg(cfg, msg)
                await asyncio.sleep(1)
            except Exception:
                log.exception("Telegram command loop error")
                await asyncio.sleep(5)
