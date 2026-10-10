"""Trust & Safety read/aggregation service over the privacy engines.

Powers the admin panel's T&S view: filtered feeds of Veil ``LeakEvent`` and Muffle
``ProfanityEvent`` rows, a repeat-offender list (by shared ``LeakStrike`` count), a
per-user safety profile, headline stats, and a strike reset. Read-only except for
``reset_strikes``. Returns raw data (querysets / dicts); the admin layer serialises.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.common.results import ServiceResult
from apps.privacy.models import LeakEvent, LeakStrike, ProfanityEvent
from apps.users.models import User

_RECENT_LIMIT = 20


def _group(queryset, field: str) -> dict[str, int]:
    return {
        row[field]: row["c"]
        for row in queryset.values(field).annotate(c=Count("id"))
    }


class TrustSafetyService:
    # -- Event feeds (return querysets for cursor pagination) ----------------

    def leak_events(
        self,
        *,
        user_id=None,
        chat_id=None,
        category=None,
        severity=None,
        action=None,
        mode=None,
    ):
        qs = LeakEvent.objects.select_related("user").all()
        if user_id:
            qs = qs.filter(user_id=user_id)
        if chat_id:
            qs = qs.filter(chat_id=chat_id)
        if category:
            qs = qs.filter(category=category.upper())
        if severity:
            qs = qs.filter(severity=severity.upper())
        if action:
            qs = qs.filter(action=action.upper())
        if mode:
            qs = qs.filter(mode=mode.lower())
        return qs

    def profanity_events(self, *, user_id=None, chat_id=None, tier=None, mode=None):
        qs = ProfanityEvent.objects.select_related("user").all()
        if user_id:
            qs = qs.filter(user_id=user_id)
        if chat_id:
            qs = qs.filter(chat_id=chat_id)
        if tier:
            qs = qs.filter(tier=tier.upper())
        if mode:
            qs = qs.filter(mode=mode.lower())
        return qs

    # -- Offenders -----------------------------------------------------------

    def offenders(self, *, min_count: int = 1, limit: int = 50, offset: int = 0) -> list[dict]:
        """Users with strikes, most severe first. Not cursor-paginated (ordering is
        by strike count); uses a simple limit/offset top-N."""
        strikes = list(
            LeakStrike.objects.select_related("user")
            .filter(count__gte=min_count)
            .order_by("-count", "-last_event_at")[offset : offset + limit]
        )
        ids = [s.user_id for s in strikes]
        leak_map = {
            r["user_id"]: r["c"]
            for r in LeakEvent.objects.filter(user_id__in=ids)
            .values("user_id")
            .annotate(c=Count("id"))
        }
        prof_map = {
            r["user_id"]: r["c"]
            for r in ProfanityEvent.objects.filter(user_id__in=ids)
            .values("user_id")
            .annotate(c=Count("id"))
        }
        return [
            {
                "user_id": str(s.user_id),
                "user_email": s.user.college_email,
                "user_name": s.user.full_name,
                "account_status": s.user.account_status,
                "strike_count": s.count,
                "last_event_at": s.last_event_at,
                "leak_count": leak_map.get(s.user_id, 0),
                "profanity_count": prof_map.get(s.user_id, 0),
            }
            for s in strikes
        ]

    # -- Per-user safety profile --------------------------------------------

    def user_safety(self, user_id) -> dict[str, Any] | None:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return None
        strike = LeakStrike.objects.filter(user=user).first()
        leaks = LeakEvent.objects.filter(user=user)
        profs = ProfanityEvent.objects.filter(user=user)
        return {
            "user": user,
            "strikes": {
                "count": strike.count if strike else 0,
                "last_event_at": strike.last_event_at if strike else None,
            },
            "counts": {
                "leak_by_category": _group(leaks, "category"),
                "leak_by_action": _group(leaks, "action"),
                "profanity_by_tier": _group(profs, "tier"),
            },
            "recent_leaks": leaks.select_related("user").order_by("-created_at")[
                :_RECENT_LIMIT
            ],
            "recent_profanity": profs.select_related("user").order_by("-created_at")[
                :_RECENT_LIMIT
            ],
        }

    # -- Stats --------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        now = timezone.now()
        d1 = now - timedelta(hours=24)
        d7 = now - timedelta(days=7)
        leaks = LeakEvent.objects.all()
        profs = ProfanityEvent.objects.all()
        return {
            "leak_events": {
                "last_24h": leaks.filter(created_at__gte=d1).count(),
                "last_7d": leaks.filter(created_at__gte=d7).count(),
                "by_category": _group(leaks, "category"),
                "by_action": _group(leaks, "action"),
                "by_mode": _group(leaks, "mode"),
            },
            "profanity_events": {
                "last_24h": profs.filter(created_at__gte=d1).count(),
                "last_7d": profs.filter(created_at__gte=d7).count(),
                "by_tier": _group(profs, "tier"),
                "by_mode": _group(profs, "mode"),
            },
            "open_offenders": LeakStrike.objects.filter(count__gte=1).count(),
        }

    # -- Actions ------------------------------------------------------------

    def reset_strikes(self, *, user, admin_id: str, notes: str = "") -> ServiceResult[dict]:
        from apps.audit.enums import ActorType
        from apps.audit.services.audit_service import AuditService

        strike, _ = LeakStrike.objects.get_or_create(user=user)
        previous = strike.count
        LeakStrike.objects.filter(pk=strike.pk).update(count=0)
        AuditService().log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action="safety.strikes_reset",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"previous_count": previous, "notes": notes},
        )
        return ServiceResult.ok(
            {"user_id": str(user.id), "strike_count": 0, "previous_count": previous}
        )
