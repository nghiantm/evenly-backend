import time
from decimal import Decimal

import httpx
from fastapi import HTTPException

_fx_cache: dict = {}
# { "EUR:USD": {"rate": Decimal("1.08"), "fetched_at": 1711900000.0} }
_FX_CACHE_TTL = 86400  # 24 hours — ECB rates update once per day


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """
    Fetch exchange rate from Frankfurter (ECB data, updates daily).
    Returns Decimal rate to convert from_currency → to_currency.
    Raises 503 if Frankfurter is unavailable.
    """
    if from_currency == to_currency:
        return Decimal("1")

    cache_key = f"{from_currency}:{to_currency}"
    now = time.time()

    cached = _fx_cache.get(cache_key)
    if cached and now - cached["fetched_at"] < _FX_CACHE_TTL:
        return cached["rate"]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.frankfurter.app/latest",
                params={"from": from_currency, "to": to_currency},
            )
            if resp.status_code == 404:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unsupported currency: {from_currency}",
                )
            resp.raise_for_status()
            data = resp.json()
            rate = Decimal(str(data["rates"][to_currency]))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Foreign currency expenses are temporarily unavailable. "
                f"Please enter the amount in {to_currency} or try again later."
            ),
        )

    _fx_cache[cache_key] = {"rate": rate, "fetched_at": now}
    return rate
