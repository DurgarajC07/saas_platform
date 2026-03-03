"""
Agents module FastAPI dependencies.

get_agent_or_404  — resolve agent UUID + org ownership in a single DB call.
                    Raises 404 if not found.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundException
from app.modules.agents.models import Agent
from app.modules.agents.repository import AgentRepository
from app.modules.rbac.dependencies import get_current_org_id


async def get_agent_or_404(
    agent_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """
    Return the requested agent if it belongs to the caller's org.
    Raises HTTP 404 otherwise.
    """
    repo = AgentRepository(db)
    agent = await repo.get_by_id_and_org(agent_id, org_id)
    if not agent:
        raise NotFoundException(f"Agent {agent_id} not found")
    return agent


# ── Convenience type alias ────────────────────────────────────────────────

AgentDep = Annotated[Agent, Depends(get_agent_or_404)]
