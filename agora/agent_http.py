"""Plain HTTP JSON door for agents that do not speak MCP. Same logic and safety rules as the MCP tools
(agora/agent_api.py): validated inputs, per-client rate limits (by IP), fenced page text, redaction, read-only.

Not mounted by default. To serve it from the main API, add to agora/api.py:

    from agora.agent_http import router as agent_router
    app.include_router(agent_router)

Routes:
  GET /api/offers?q=...&country=fi&max_price_eur=900&conditions=used,refurbished&limit=10
  GET /api/offer?url=...            one offer Agora already read (never fetches the URL)
  GET /api/offer/receipt?url=...    its receipt
Written at Junction 2026.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from agora import agent_api

router = APIRouter(tags=["agents"])


def _client(request: Request) -> str:
    return "http:" + (request.client.host if request.client else "unknown")


async def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        res = fn(*args, **kwargs)
        if hasattr(res, "__await__"):
            res = await res
        return res
    except agent_api.RateLimited as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "60"}) from e
    except agent_api.AgentError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/api/offers")
async def api_offers(request: Request,
                     q: str = Query(..., min_length=2, max_length=agent_api.MAX_QUERY, description="what you want"),
                     country: str | None = Query(None, max_length=40, description="ISO code, e.g. fi, de"),
                     max_price_eur: float | None = Query(None, gt=0, description="all-in cap in EUR"),
                     conditions: str | None = Query(None, max_length=80,
                                                    description="comma list: new,refurbished,used,rental,service"),
                     limit: int = Query(agent_api.DEFAULT_LIMIT, ge=1, le=agent_api.MAX_LIMIT)) -> Any:
    """Offers for `q`, ranked by all-in price, each with a link to the listing page. Read-only."""
    return await _run(agent_api.find_offers, q, country, max_price_eur, conditions, limit, client=_client(request))


@router.get("/api/offer")
async def api_offer(request: Request, url: str = Query(..., max_length=agent_api.MAX_URL)) -> Any:
    return await _run(agent_api.get_offer, url, client=_client(request))


@router.get("/api/offer/receipt")
async def api_offer_receipt(request: Request, url: str = Query(..., max_length=agent_api.MAX_URL)) -> Any:
    return await _run(agent_api.explain_price, url, client=_client(request))
