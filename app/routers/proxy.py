import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

_proxy_fx_cache: dict = {}
_PROXY_FX_CACHE_TTL = 60  # seconds


@router.get("/fx")
async def proxy_fx(
    from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
    to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    _: User = Depends(get_current_user),
) -> dict:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return {"rate": 1.0}

    cache_key = f"{from_currency}:{to_currency}"
    now = time.time()
    cached = _proxy_fx_cache.get(cache_key)
    if cached and now - cached["fetched_at"] < _PROXY_FX_CACHE_TTL:
        return {"rate": cached["rate"]}

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.frankfurter.app/latest",
                params={"from": from_currency, "to": to_currency},
            )
    except Exception as exc:
        logger.error("FX proxy request failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail="FX service unreachable")

    if resp.status_code != 200:
        logger.error("FX proxy: Frankfurter returned %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail=f"FX service returned {resp.status_code}")

    data = resp.json()
    rates = data.get("rates", {})
    if to_currency not in rates:
        raise HTTPException(status_code=400, detail=f"Unsupported currency pair: {from_currency}/{to_currency}")

    rate = float(rates[to_currency])
    _proxy_fx_cache[cache_key] = {"rate": rate, "fetched_at": now}
    return {"rate": rate}
