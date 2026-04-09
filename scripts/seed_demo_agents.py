#!/usr/bin/env python3
"""
Seed Demo Agents (Day 16.2)
============================
Creates 4 fully-configured demo agents that cover every agent type.
Designed for investor / client demos — safe to re-run (idempotent by slug).

Demo agents
───────────
  Aria — Receptionist     conversational  af_heart  (warm)
  DocuBot — FAQ           rag_bot         bf_emma   (professional)
  OrderBot — CRM          db_bot          am_adam   (neutral)
  Announcer — IVR         speaker_only    af_sky    (clear)

Usage
─────
    uv run python scripts/seed_demo_agents.py

The script uses the FIRST active organisation found in the database as the
owner for all demo agents.  Pass --org-slug=<slug> to target a specific org.

    uv run python scripts/seed_demo_agents.py --org-slug=acme-corp
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.config import get_settings
from app.core import all_models  # noqa: F401 — populate SQLAlchemy mapper registry
from app.core.database import create_engine, create_session_factory
from app.modules.agents.models import Agent
from app.modules.tenancy.models import Organization


# ── Demo agent definitions ────────────────────────────────────────────────────

@dataclass
class DemoAgent:
    slug: str
    name: str
    agent_type: str
    tts_voice: str
    system_prompt: str
    welcome_message: str
    language: str = "en"
    llm_model: str = "qwen2.5:3b"
    temperature: float = 0.7
    max_tokens: int = 512
    qdrant_collection: str | None = None
    tools_json: list | None = None
    metadata_: dict = field(default_factory=dict)
    noise_removal_level: str = "rnnoise"


DEMO_AGENTS: list[DemoAgent] = [
    # ── 1. Aria — Receptionist (conversational) ───────────────────────────────
    DemoAgent(
        slug="demo-aria-receptionist",
        name="Aria — Receptionist",
        agent_type="conversational",
        tts_voice="af_heart",
        language="en",
        llm_model="qwen2.5:7b",
        temperature=0.6,
        system_prompt=(
            "You are Aria, a warm and professional virtual receptionist for Acme Corp. "
            "Your job is to greet callers, understand their intent, and route them to the "
            "right department. Keep responses concise — under 30 words per turn. "
            "Available departments: Sales (ext 101), Support (ext 102), Billing (ext 103).\n"
            "When a caller asks to be transferred say: 'Let me transfer you now. Please hold.'"
        ),
        welcome_message=(
            "Hello, thank you for calling Acme Corp. "
            "I'm Aria, your virtual receptionist. How can I help you today?"
        ),
        metadata_={
            "demo": True,
            "use_case": "inbound_receptionist",
            "transfer_map": {"sales": "101", "support": "102", "billing": "103"},
        },
    ),

    # ── 2. DocuBot — FAQ / RAG Bot ──────────────────────────────────────────
    DemoAgent(
        slug="demo-docubot-faq",
        name="DocuBot — FAQ",
        agent_type="rag_bot",
        tts_voice="bf_emma",
        language="en",
        llm_model="qwen2.5:7b",
        temperature=0.3,
        qdrant_collection="demo_policy_docs",
        system_prompt=(
            "You are DocuBot, a professional FAQ assistant for Acme Corp. "
            "Answer questions ONLY from the retrieved policy documents. "
            "If the answer is not in the documents, say: 'I don't have that "
            "information in my knowledge base. Please email support@acme.com.' "
            "Always cite the document name when answering. "
            "Keep answers under 60 words."
        ),
        welcome_message=(
            "Hi! I'm DocuBot. I can answer questions about Acme Corp policies "
            "and procedures. What would you like to know?"
        ),
        metadata_={
            "demo": True,
            "use_case": "rag_faq",
            "kb_source": "policy_pdf",
            "rag_top_k": 5,
        },
    ),

    # ── 3. OrderBot — CRM / DB Bot ───────────────────────────────────────────
    DemoAgent(
        slug="demo-orderbot-crm",
        name="OrderBot — CRM",
        agent_type="db_bot",
        tts_voice="am_adam",
        language="en",
        llm_model="qwen2.5:7b",
        temperature=0.2,
        system_prompt=(
            "You are OrderBot, a neutral and efficient order status assistant. "
            "When a caller provides an order number, use the lookup_order tool to "
            "retrieve the status. Report status, estimated delivery date, and "
            "tracking number clearly and concisely. "
            "Never make up order details — only report what the tool returns. "
            "If the order is not found, say: 'I couldn't find that order number. "
            "Please double-check and try again.'"
        ),
        welcome_message=(
            "Hello! I'm OrderBot. I can check the status of your order. "
            "Please provide your order number when ready."
        ),
        tools_json=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "description": "Look up an order by order number from the CRM database",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_number": {
                                "type": "string",
                                "description": "The order number, e.g. ORD-12345",
                            }
                        },
                        "required": ["order_number"],
                    },
                },
            }
        ],
        metadata_={
            "demo": True,
            "use_case": "crm_order_lookup",
            "allowed_tables": ["orders", "order_items", "shipments"],
            "http_api": "https://api.acme-demo.com/orders",
        },
    ),

    # ── 4. Announcer — IVR (speaker_only) ───────────────────────────────────
    DemoAgent(
        slug="demo-announcer-ivr",
        name="Announcer — IVR",
        agent_type="speaker_only",
        tts_voice="af_sky",
        language="en",
        llm_model="qwen2.5:3b",
        temperature=0.1,
        system_prompt=(
            "You are an IVR announcer. Read the menu options clearly and naturally. "
            "After the greeting, announce: "
            "'Press 1 for Sales. Press 2 for Support. Press 3 for Billing. "
            "Press 0 to repeat this menu.' "
            "Do not engage in conversation beyond the menu."
        ),
        welcome_message=(
            "Thank you for calling Acme Corp. "
            "Please listen carefully to the following options."
        ),
        metadata_={
            "demo": True,
            "use_case": "ivr_menu",
            "dtmf_map": {"1": "sales", "2": "support", "3": "billing", "0": "repeat_menu"},
            "noise_removal_level": "none",
        },
        noise_removal_level="none",
    ),
]


# ── Seed function ─────────────────────────────────────────────────────────────

async def seed_demo_agents(
    session,
    org: Organization,
) -> None:
    now = datetime.now(UTC)

    for defn in DEMO_AGENTS:
        existing = await session.execute(
            select(Agent).where(
                Agent.slug == defn.slug,
                Agent.org_id == org.id,
                Agent.deleted_at.is_(None),
            )
        )
        agent = existing.scalar_one_or_none()

        if agent is not None:
            # Refresh mutable fields on re-run
            agent.name = defn.name
            agent.system_prompt = defn.system_prompt
            agent.welcome_message = defn.welcome_message
            agent.tts_voice = defn.tts_voice
            agent.llm_model = defn.llm_model
            agent.temperature = defn.temperature
            agent.tools_json = defn.tools_json
            agent.qdrant_collection = defn.qdrant_collection
            agent.metadata_ = defn.metadata_
            agent.updated_at = now
            print(f"  [agent] UPDATED  {defn.slug!r}")
        else:
            agent = Agent(
                id=uuid4(),
                org_id=org.id,
                created_by=None,
                name=defn.name,
                slug=defn.slug,
                agent_type=defn.agent_type,
                status="active",
                llm_model=defn.llm_model,
                system_prompt=defn.system_prompt,
                temperature=defn.temperature,
                max_tokens=defn.max_tokens,
                language=defn.language,
                tts_voice=defn.tts_voice,
                tts_speed=1.0,
                vad_threshold=0.5,
                min_speech_ms=250,
                silence_ms=800,
                allow_interruptions=True,
                noise_removal_level=defn.noise_removal_level,
                qdrant_collection=defn.qdrant_collection,
                rag_top_k=3,
                tools_json=defn.tools_json,
                welcome_message=defn.welcome_message,
                max_call_duration_sec=600,
                record_calls=True,
                metadata_=defn.metadata_,
                created_at=now,
                updated_at=now,
            )
            session.add(agent)
            print(f"  [agent] CREATED  {defn.slug!r}  ({defn.agent_type})")

    await session.commit()
    print(f"\nDemo agents seeded for org '{org.slug}' — {len(DEMO_AGENTS)} agents total.")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main(org_slug: str | None = None) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        if org_slug:
            result = await session.execute(
                select(Organization).where(
                    Organization.slug == org_slug,
                    Organization.is_active.is_(True),
                )
            )
            org = result.scalar_one_or_none()
            if org is None:
                print(f"ERROR: No active organisation with slug '{org_slug}' found.", file=sys.stderr)
                sys.exit(1)
        else:
            result = await session.execute(
                select(Organization)
                .where(Organization.is_active.is_(True))
                .order_by(Organization.created_at.asc())
                .limit(1)
            )
            org = result.scalar_one_or_none()
            if org is None:
                print(
                    "ERROR: No active organisation found.\n"
                    "Create one first with: uv run python scripts/create_superuser.py",
                    file=sys.stderr,
                )
                sys.exit(1)

        print(f"Seeding demo agents for org: {org.slug!r} ({org.id})")
        await seed_demo_agents(session, org)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo AI voice agents")
    parser.add_argument(
        "--org-slug",
        default=None,
        help="Slug of the target organisation (default: first active org)",
    )
    args = parser.parse_args()
    asyncio.run(main(org_slug=args.org_slug))
