import asyncio
import time

class RateLimiter:
    def __init__(self, calls_per_second: float = 1.0):
        self.interval = 1.0 / calls_per_second
        self.last_call = 0

    async def acquire(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)
        self.last_call = time.time()