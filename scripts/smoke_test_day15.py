#!/usr/bin/env python3
"""
Smoke test — Day 15: Platform Admin APIs
=========================================
Validates:
  1. All Day-15 source files exist on disk.
  2. Dashboard module schemas, service, router are importable.
  3. Dashboard router exposes the expected endpoint paths.
  4. agents.events module exports the required publish_* functions.
  5. Billing schemas BillingUsageResponse / InvoicePreviewResponse exist.
  6. BillingService has get_usage() and get_invoice_preview() methods.
  7. Billing router has /usage and /invoice-preview routes.
  8. CallLogService constructor accepts a redis parameter.
  9. Dashboard router is registered in main.py.
 10. requirements.txt contains pynvml and sse-starlette.
 11. DashboardService._pct() logic.
 12. AdminService.gpu_status() falls back gracefully without NVIDIA HW.

Exit code 0 = all checks passed.
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f" — {detail}" if detail else "")
        print(f"  {FAIL}  {msg}")
        failures.append(msg)


# ── 1. File existence ────────────────────────────────────────────────────────

print("\n[1] File existence")

expected_files = [
    "app/modules/dashboard/__init__.py",
    "app/modules/dashboard/schemas.py",
    "app/modules/dashboard/repository.py",
    "app/modules/dashboard/service.py",
    "app/modules/dashboard/router.py",
    "app/modules/agents/events.py",
]
for path in expected_files:
    check(f"exists: {path}", (ROOT / path).exists())

# ── 2. Dashboard module imports ──────────────────────────────────────────────

print("\n[2] Dashboard module imports")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

try:
    from app.modules.dashboard import schemas as dash_schemas

    check("dashboard.schemas importable", True)
    check(
        "OverviewResponse in schemas",
        hasattr(dash_schemas, "OverviewResponse"),
    )
    check(
        "LatencyResponse in schemas",
        hasattr(dash_schemas, "LatencyResponse"),
    )
    check(
        "GPUStatusResponse in schemas",
        hasattr(dash_schemas, "GPUStatusResponse"),
    )
    check(
        "QueueStatusResponse in schemas",
        hasattr(dash_schemas, "QueueStatusResponse"),
    )
except Exception as exc:
    check("dashboard.schemas importable", False, str(exc))

try:
    from app.modules.dashboard.service import AdminService, DashboardService

    check("DashboardService importable", True)
    check("AdminService importable", True)
    check("DashboardService._pct static", callable(getattr(DashboardService, "_pct", None)))
    check("AdminService.gpu_status static", callable(getattr(AdminService, "gpu_status", None)))
    check("AdminService.queue_status static", callable(getattr(AdminService, "queue_status", None)))
except Exception as exc:
    check("dashboard.service importable", False, str(exc))

try:
    from app.modules.dashboard.router import router as dash_router

    check("dashboard.router importable", True)
    paths = {r.path for r in dash_router.routes}
    check("/dashboard/overview route", "/dashboard/overview" in paths, str(paths))
    check("/dashboard/latency route", "/dashboard/latency" in paths, str(paths))
    check("/dashboard/call-volume route", "/dashboard/call-volume" in paths, str(paths))
    check("/dashboard/agent-performance route", "/dashboard/agent-performance" in paths, str(paths))
    check("/calls/live SSE route", "/calls/live" in paths, str(paths))
    check("/admin/gpu-status route", "/admin/gpu-status" in paths, str(paths))
    check("/admin/queue-status route", "/admin/queue-status" in paths, str(paths))
    check("/admin/model-benchmark route", "/admin/model-benchmark" in paths, str(paths))
except Exception as exc:
    check("dashboard.router importable", False, str(exc))

# ── 3. agents.events functions ───────────────────────────────────────────────

print("\n[3] agents.events")

try:
    from app.modules.agents import events as ag_events

    check("agents.events importable", True)
    for fn in [
        "publish_call_started",
        "publish_call_ended",
        "publish_call_failed",
        "publish_limit_warning",
        "publish_limit_exceeded",
        "publish_kb_ingestion_complete",
    ]:
        check(f"events.{fn} present", hasattr(ag_events, fn))
        if hasattr(ag_events, fn):
            check(
                f"events.{fn} is coroutine",
                inspect.iscoroutinefunction(getattr(ag_events, fn)),
            )
except Exception as exc:
    check("agents.events importable", False, str(exc))

# ── 4. Billing schemas ───────────────────────────────────────────────────────

print("\n[4] Billing schemas")

try:
    from app.modules.billing.schemas import BillingUsageResponse, InvoiceLineItem, InvoicePreviewResponse

    check("BillingUsageResponse importable", True)
    check("InvoicePreviewResponse importable", True)
    check("InvoiceLineItem importable", True)

    fields_usage = BillingUsageResponse.model_fields
    for f in ["org_id", "period", "used_minutes", "allowed_minutes", "credit_balance", "plan_name"]:
        check(f"BillingUsageResponse.{f} field", f in fields_usage)

    fields_preview = InvoicePreviewResponse.model_fields
    for f in ["org_id", "period", "line_items", "subtotal", "currency", "estimated_at"]:
        check(f"InvoicePreviewResponse.{f} field", f in fields_preview)
except Exception as exc:
    check("billing schemas new classes", False, str(exc))

# ── 5. BillingService methods ────────────────────────────────────────────────

print("\n[5] BillingService methods")

try:
    from app.modules.billing.service import BillingService

    check("BillingService.get_usage method", hasattr(BillingService, "get_usage"))
    check(
        "BillingService.get_usage is coro",
        inspect.iscoroutinefunction(getattr(BillingService, "get_usage", None)),
    )
    check(
        "BillingService.get_invoice_preview method",
        hasattr(BillingService, "get_invoice_preview"),
    )
    check(
        "BillingService.get_invoice_preview is coro",
        inspect.iscoroutinefunction(getattr(BillingService, "get_invoice_preview", None)),
    )
except Exception as exc:
    check("BillingService methods", False, str(exc))

# ── 6. Billing router new endpoints ─────────────────────────────────────────

print("\n[6] Billing router new endpoints")

try:
    from app.modules.billing.router import router as billing_router

    paths = {r.path for r in billing_router.routes}
    check("/usage billing route", "/usage" in paths, str(paths))
    check("/invoice-preview billing route", "/invoice-preview" in paths, str(paths))
except Exception as exc:
    check("billing.router importable", False, str(exc))

# ── 7. CallLogService redis param ────────────────────────────────────────────

print("\n[7] CallLogService accepts redis parameter")

try:
    from app.modules.agents.service import CallLogService

    sig = inspect.signature(CallLogService.__init__)
    check("CallLogService.__init__ has redis param", "redis" in sig.parameters)
except Exception as exc:
    check("CallLogService.__init__ signature", False, str(exc))

# ── 8. main.py dashboard registration ───────────────────────────────────────

print("\n[8] main.py dashboard router registration")

main_text = (ROOT / "app/main.py").read_text()
check("dashboard router import in main.py", "dashboard.router" in main_text)
check("dashboard router include_router in main.py", "dashboard_router" in main_text and "include_router" in main_text)

# ── 9. requirements.txt entries ──────────────────────────────────────────────

print("\n[9] requirements.txt entries")

req_text = (ROOT / "requirements.txt").read_text()
check("pynvml in requirements.txt", "pynvml" in req_text)
check("sse-starlette in requirements.txt", "sse-starlette" in req_text)

# ── 10. DashboardService._pct logic ─────────────────────────────────────────

print("\n[10] DashboardService._pct logic")

try:
    from app.modules.dashboard.service import DashboardService

    check("_pct(0, 0) == 0.0", DashboardService._pct(0, 0) == 0.0)
    check("_pct(50, 100) == 50.0", DashboardService._pct(50, 100) == 50.0)
    check("_pct(100, 100) == 100.0", DashboardService._pct(100, 100) == 100.0)
except Exception as exc:
    check("DashboardService._pct", False, str(exc))

# ── 11. AdminService.gpu_status graceful fallback ────────────────────────────

print("\n[11] AdminService.gpu_status graceful fallback")

try:
    from unittest.mock import patch

    from app.modules.dashboard.service import AdminService

    with patch.dict("sys.modules", {"pynvml": None}):
        result = AdminService.gpu_status()
    check("gpu_status returns nvml_available=False without pynvml", result.nvml_available is False)
    check("gpu_status devices is empty list", result.devices == [])
except Exception as exc:
    check("AdminService.gpu_status fallback", False, str(exc))

# ── Summary ──────────────────────────────────────────────────────────────────

print()
if failures:
    print(f"{'─'*60}")
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  • {f}")
    sys.exit(1)
else:
    total = sum(
        1
        for line in [
            "File existence", "Dashboard module imports", "agents.events",
            "Billing schemas", "BillingService methods", "Billing router",
            "CallLogService", "main.py", "requirements.txt",
            "DashboardService", "AdminService",
        ]
    )
    print("ALL CHECKS PASSED  ✓ — Day 15 smoke test complete")
    sys.exit(0)
