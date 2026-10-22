"""Routers for the document, import, people, planning, reporting and privacy modules."""
from app.modules.cards.router import router as cards
from app.modules.documents.router import router as documents
from app.modules.imports.router import router as imports
from app.modules.integrations.router import router as integrations
from app.modules.notifications.router import router as notifications
from app.modules.people.router import router as people
from app.modules.planning.router import router as planning

ROUTERS = [cards, documents, imports, integrations, people, planning, notifications]

try:
    from app.modules.reports.router import router as reports
    from app.modules.prices.router import router as prices
    from app.modules.privacy.router import router as privacy

    ROUTERS += [reports, prices, privacy]
except ImportError as exc:  # pragma: no cover - modules land incrementally
    if "app.modules.reports" not in str(exc) and "app.modules.prices.router" not in str(exc) and "app.modules.privacy" not in str(exc):
        raise
