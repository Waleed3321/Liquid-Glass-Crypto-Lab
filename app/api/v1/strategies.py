"""Strategy configuration and decision log endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session_dep
from app.core.security import require_admin
from app.repositories.system import SystemRepository
from app.schemas.settings import StrategySettingsIn
from app.services.settings_service import load_strategy_config, save_strategy_config
from app.strategies.config import StrategyConfig

router = APIRouter(prefix="/strategies", tags=["strategies"])

HARD_CAPS = {
    "initial_balance_usd": 10.0,
    "max_open_positions": 3,
    "max_position_usd": 2.5,
    "daily_loss_limit_usd": 0.5,
    "max_price_impact_pct": 1.0,
}

STRATEGY_META = {
    "id": "A",
    "version": "A-1.0",
    "name": "Conservative Momentum Pullback",
    "summary": (
        "Waits for at least ten minutes of observation, requires an established one-hour "
        "uptrend, buys a controlled pullback that has stabilised, and refuses vertical candles, "
        "thin liquidity, unsafe tokens, incomplete security data and overly expensive round trips."
    ),
    "entry_gates": [
        "Observation window and snapshot density",
        "One-hour trend between the configured bounds",
        "Pullback inside the configured band",
        "Stabilisation inside the configured band",
        "Anti-vertical guard (5m change, price vs SMA, candle slope)",
        "Liquidity floor and no liquidity deterioration",
        "Buy/sell activity inside the configured ratio",
        "Opportunity score, data confidence and signal strength",
        "Security eligible with no missing critical fields",
        "Round-trip cost under the configured ceiling",
    ],
    "exit_rules": [
        "Stop loss at the configured percentage",
        "Trailing stop after protection is armed",
        "Security breakdown",
        "Liquidity collapse",
        "Momentum breakdown",
        "Take profit: half at the half target, remainder at the full target",
    ],
}


def _config_payload(config: StrategyConfig) -> dict:
    return {
        "strategy": STRATEGY_META,
        "settings": config.public_dict(),
        "defaults": StrategyConfig().public_dict(),
        "hard_caps": HARD_CAPS,
        "strategy_version": config.version,
        "paper_only": True,
    }


@router.get("")
async def get_strategy(
    decisions: int = Query(default=25, ge=0, le=200),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    config = await load_strategy_config(session)
    payload = _config_payload(config)
    rows = await SystemRepository(session).recent_decisions(limit=decisions) if decisions else []
    payload["decisions"] = [
        {
            "id": row.id,
            "token_id": row.token_id,
            "position_id": row.position_id,
            "action": row.action,
            "reason_codes": row.reason_codes or [],
            "metrics": row.metrics or {},
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return payload


@router.put("/settings", dependencies=[Depends(require_admin)])
async def update_strategy_settings(
    payload: StrategySettingsIn,
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    config = await save_strategy_config(session, payload.overrides())
    await session.commit()
    return _config_payload(config)


@router.post("/settings/reset", dependencies=[Depends(require_admin)])
async def reset_strategy_settings(session: AsyncSession = Depends(get_session_dep)) -> dict:
    repo = SystemRepository(session)
    await repo.set_setting("strategy.config", StrategyConfig().model_dump())
    await session.commit()
    return _config_payload(StrategyConfig())


@router.get("/decisions")
async def decision_log(
    limit: int = Query(default=50, ge=1, le=300),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    rows = await SystemRepository(session).recent_decisions(limit=limit)
    return {
        "decisions": [
            {
                "id": row.id,
                "token_id": row.token_id,
                "position_id": row.position_id,
                "strategy": row.strategy,
                "action": row.action,
                "reason_codes": row.reason_codes or [],
                "metrics": row.metrics or {},
                "note": row.note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/limits")
async def strategy_limits() -> JSONResponse:
    return JSONResponse(HARD_CAPS)
