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
from apps.privacy.enums import SuspicionReviewStatus, SuspicionTier
from apps.privacy.models import (
    LeakEvent,
    LeakStrike,
    ProfanityEvent,
    SuspicionEvent,
    UserSuspicionProfile,
)
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
        source=None,
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
        if source:
            qs = qs.filter(source=source.upper())
        return qs

    def suspicion_events(self, *, user_id=None, chat_id=None, signal=None, min_score=None):
        qs = SuspicionEvent.objects.select_related("user").all()
        if user_id:
            qs = qs.filter(user_id=user_id)
        if chat_id:
            qs = qs.filter(chat_id=chat_id)
        if signal:
            qs = qs.filter(top_signal=signal.upper())
        if min_score:
            qs = qs.filter(score__gte=min_score)
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

    def suspicion_offenders(
        self,
        *,
        min_score: int = 1,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Users by suspicion score, highest first. Optionally filter by the
        admin review status (e.g. only UNREVIEWED)."""
        qs = UserSuspicionProfile.objects.select_related("user").filter(
            score__gte=min_score
        )
        if review_status:
            qs = qs.filter(review_status=review_status.upper())
        # Rank by the decayed, ambient-excluded PRIORITY score (then tier), so normal
        # romanized-Hindi / non-Latin / gibberish chat never ranks a legitimate user.
        profiles = list(
            qs.order_by("-priority_score", "-last_event_at")[offset : offset + limit]
        )
        return [
            {
                "user_id": str(p.user_id),
                "user_email": p.user.college_email,
                "user_name": p.user.full_name,
                "account_status": p.user.account_status,
                "score": p.score,
                "priority_score": p.priority_score,
                "tier": p.tier,
                "event_count": p.event_count,
                "last_event_at": p.last_event_at,
                "review_status": p.review_status,
            }
            for p in profiles
        ]

    @staticmethod
    def _suspicion_class_counts(suspicions) -> dict[str, int]:
        """Count a user's suspicion events by signal CLASS (ambient / structural /
        pii / behavioral), so an admin sees whether the accumulation is just ambient
        noise or real PII tells. Derived from the stored per-signal class."""
        from apps.privacy.suspicion_data import SIGNAL_CLASS

        counts: dict[str, int] = {}
        for ev in suspicions.values_list("signals", flat=True):
            seen: set[str] = set()
            for s in ev or []:
                cls = s.get("class") or SIGNAL_CLASS.get(s.get("signal", ""), "pii")
                if cls not in seen:  # one count per class per event
                    counts[cls] = counts.get(cls, 0) + 1
                    seen.add(cls)
        return counts

    # -- Per-user safety profile --------------------------------------------

    def user_safety(self, user_id) -> dict[str, Any] | None:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return None
        strike = LeakStrike.objects.filter(user=user).first()
        leaks = LeakEvent.objects.filter(user=user)
        profs = ProfanityEvent.objects.filter(user=user)
        suspicions = SuspicionEvent.objects.filter(user=user)
        profile = UserSuspicionProfile.objects.filter(user=user).first()
        return {
            "user": user,
            "strikes": {
                "count": strike.count if strike else 0,
                "last_event_at": strike.last_event_at if strike else None,
            },
            "counts": {
                "leak_by_category": _group(leaks, "category"),
                "leak_by_action": _group(leaks, "action"),
                "leak_by_source": _group(leaks, "source"),
                "profanity_by_tier": _group(profs, "tier"),
                "suspicion_by_signal": _group(suspicions, "top_signal"),
            },
            "suspicion": {
                "score": profile.score if profile else 0,
                "priority_score": profile.priority_score if profile else 0,
                "tier": profile.tier if profile else "CLEAN",
                "event_count": profile.event_count if profile else 0,
                "last_event_at": profile.last_event_at if profile else None,
                "by_class": self._suspicion_class_counts(suspicions),
                "review_status": (
                    profile.review_status
                    if profile
                    else SuspicionReviewStatus.UNREVIEWED.value
                ),
                "reviewed_by": profile.reviewed_by if profile else "",
                "reviewed_at": profile.reviewed_at if profile else None,
                "notes": profile.notes if profile else "",
            },
            "recent_leaks": leaks.select_related("user").order_by("-created_at")[
                :_RECENT_LIMIT
            ],
            "recent_profanity": profs.select_related("user").order_by("-created_at")[
                :_RECENT_LIMIT
            ],
            "recent_suspicions": suspicions.select_related("user").order_by(
                "-created_at"
            )[:_RECENT_LIMIT],
        }

    # -- Stats --------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        now = timezone.now()
        d1 = now - timedelta(hours=24)
        d7 = now - timedelta(days=7)
        leaks = LeakEvent.objects.all()
        profs = ProfanityEvent.objects.all()
        suspicions = SuspicionEvent.objects.all()
        return {
            "leak_events": {
                "last_24h": leaks.filter(created_at__gte=d1).count(),
                "last_7d": leaks.filter(created_at__gte=d7).count(),
                "by_category": _group(leaks, "category"),
                "by_action": _group(leaks, "action"),
                "by_mode": _group(leaks, "mode"),
                "by_source": _group(leaks, "source"),
            },
            "profanity_events": {
                "last_24h": profs.filter(created_at__gte=d1).count(),
                "last_7d": profs.filter(created_at__gte=d7).count(),
                "by_tier": _group(profs, "tier"),
                "by_mode": _group(profs, "mode"),
            },
            "suspicion_events": {
                "last_24h": suspicions.filter(created_at__gte=d1).count(),
                "last_7d": suspicions.filter(created_at__gte=d7).count(),
                "by_signal": _group(suspicions, "top_signal"),
            },
            "open_offenders": LeakStrike.objects.filter(count__gte=1).count(),
            "suspicion_unreviewed": UserSuspicionProfile.objects.filter(
                score__gte=1, review_status=SuspicionReviewStatus.UNREVIEWED.value
            ).count(),
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

    def reset_suspicion_score(
        self, *, user, admin_id: str, notes: str = ""
    ) -> ServiceResult[dict]:
        """Clear a user's accumulated suspicion (score + priority + tier) and mark it
        CLEARED. Lets an admin wipe a false accumulation in one click. Audited.
        Still advisory only: this does not change the account."""
        from apps.audit.enums import ActorType
        from apps.audit.services.audit_service import AuditService

        profile, _ = UserSuspicionProfile.objects.get_or_create(user=user)
        previous = profile.score
        profile.score = 0
        profile.priority_score = 0
        profile.tier = SuspicionTier.CLEAN.value
        profile.review_status = SuspicionReviewStatus.CLEARED.value
        profile.reviewed_by = admin_id
        profile.reviewed_at = timezone.now()
        if notes:
            profile.notes = notes
        profile.save(
            update_fields=[
                "score", "priority_score", "tier", "review_status",
                "reviewed_by", "reviewed_at", "notes", "updated_at",
            ]
        )
        AuditService().log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action="safety.suspicion_score_reset",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"previous_score": previous, "notes": notes},
        )
        return ServiceResult.ok(
            {"user_id": str(user.id), "score": 0, "previous_score": previous}
        )

    def review_suspicion(
        self, *, user, status: str, admin_id: str, notes: str = ""
    ) -> ServiceResult[dict]:
        """Admin assessment of a user's accumulated suspicion. Sets the review
        status (REVIEWED / CLEARED / ACTIONED / UNREVIEWED) + notes, audits it.
        Advisory only: this never changes the account (use suspend/ban for that)."""
        from apps.audit.enums import ActorType
        from apps.audit.services.audit_service import AuditService

        status = (status or "").upper()
        if status not in set(SuspicionReviewStatus.values):
            return ServiceResult.fail("VALIDATION_ERROR", "Invalid review status.")

        profile, _ = UserSuspicionProfile.objects.get_or_create(user=user)
        profile.review_status = status
        profile.reviewed_by = admin_id
        profile.reviewed_at = timezone.now()
        profile.notes = notes or ""
        profile.save(
            update_fields=["review_status", "reviewed_by", "reviewed_at", "notes", "updated_at"]
        )
        AuditService().log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action="safety.suspicion_reviewed",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"review_status": status, "notes": notes},
        )
        return ServiceResult.ok(
            {
                "user_id": str(user.id),
                "review_status": status,
                "score": profile.score,
            }
        )
