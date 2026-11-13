"""
Admin serializers.

Unlike the user-facing serializers, these expose moderation-relevant detail:
verification document URLs (admins may review them), report admin notes, and
raw message content as chat evidence.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.colleges.models import College
from apps.common.media import resolve_media_url
from apps.configuration.models import AppConfig, FeatureFlag
from apps.messaging.enums import MediaStatus
from apps.messaging.models import Message
from apps.messaging.realtime import reactions_payload
from apps.privacy.enums import SuspicionReviewStatus
from apps.privacy.models import LeakEvent, ProfanityEvent, SuspicionEvent
from apps.reports.enums import ResolutionAction
from apps.reports.models import Report
from apps.users.models import User
from apps.verification.models import VerificationRequest


def _public_forensics(rep) -> dict:
    """Admin-facing slice of a stored forensic report: the verdict + signals, with
    the raw hashes kept server-side (not needed by the panel)."""
    rep = rep if isinstance(rep, dict) else {}
    return {"overall": rep.get("overall", "ok"), "signals": rep.get("signals", [])}


class AdminVerificationRequestSerializer(serializers.ModelSerializer):
    """Verification request with signed document URLs for review."""

    user_id = serializers.UUIDField(read_only=True)
    reviewed_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    college_id_image_url = serializers.SerializerMethodField()
    gesture_selfie_image_url = serializers.SerializerMethodField()
    # Resolved {code, label, emoji} for the requested gesture (raw code stays in
    # gesture_type for back-compat). Falls back gracefully for historical codes no
    # longer in the pool, so old attempts still render.
    gesture = serializers.SerializerMethodField()
    # Report-only image forensics, shown on EVERY verification (any status).
    # forensics_overall is a cheap badge (from stored JSON); forensics is the full
    # per-image report rendered below the image. Duplicate detection (a live query)
    # is added only on the detail view to keep the list cheap. AI_BRIDGE / EXTERNAL.
    forensics_overall = serializers.SerializerMethodField()
    forensics = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
            "user_id",
            "attempt_number",
            "status",
            "gesture_type",
            "gesture",
            "college_id_image_url",
            "gesture_selfie_image_url",
            "review_notes",
            "reviewed_by_id",
            "submitted_at",
            "reviewed_at",
            "created_at",
            "forensics_overall",
            "forensics",
        ]
        read_only_fields = fields

    def get_college_id_image_url(self, obj: VerificationRequest) -> str:
        return resolve_media_url(obj.college_id_image_url)

    def get_gesture_selfie_image_url(self, obj: VerificationRequest) -> str:
        return resolve_media_url(obj.gesture_selfie_image_url)

    def get_gesture(self, obj: VerificationRequest) -> dict | None:
        from apps.configuration.services.configuration_service import (
            ConfigurationService,
        )

        return ConfigurationService().get_gesture(obj.gesture_type)

    def get_forensics_overall(self, obj: VerificationRequest) -> str:
        for rep in (obj.gesture_selfie_forensics, obj.college_id_forensics):
            if isinstance(rep, dict) and rep.get("overall") == "attention":
                return "attention"
        return "ok"

    def get_forensics(self, obj: VerificationRequest) -> dict:
        return {
            "overall": self.get_forensics_overall(obj),
            "selfie": _public_forensics(obj.gesture_selfie_forensics),
            "college_id": _public_forensics(obj.college_id_forensics),
            "duplicates": [],
        }


class AdminVerificationDetailSerializer(AdminVerificationRequestSerializer):
    """Detail view: adds the applicant's name + profile photo so the admin can
    judge identity (reject for a bad name/DP vs. resubmit for a bad document).
    Detail-only — the queue serializer stays lean (no per-item photo SAS)."""

    full_name = serializers.CharField(source="user.full_name", read_only=True)
    profile_photo_url = serializers.SerializerMethodField()
    date_of_birth = serializers.DateField(
        source="user.date_of_birth", read_only=True, allow_null=True
    )
    age = serializers.IntegerField(source="user.age", read_only=True, allow_null=True)

    class Meta(AdminVerificationRequestSerializer.Meta):
        fields = AdminVerificationRequestSerializer.Meta.fields + [
            "full_name",
            "profile_photo_url",
            "date_of_birth",
            "age",
        ]
        read_only_fields = fields

    def get_profile_photo_url(self, obj: VerificationRequest) -> str:
        return resolve_media_url(obj.user.profile_photo_url)

    def get_forensics(self, obj: VerificationRequest) -> dict:
        # Detail view adds the one live signal: cross-user selfie reuse.
        from apps.verification.services.verification_service import VerificationService

        report = super().get_forensics(obj)
        duplicates = VerificationService().find_selfie_duplicates(obj)
        report["duplicates"] = duplicates
        if duplicates:
            report["overall"] = "attention"
        return report


class ReviewActionSerializer(serializers.Serializer):
    """Optional reviewer notes for approve/reject/resubmission."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AdminReportSerializer(serializers.ModelSerializer):
    """Full report view including moderation fields."""

    chat_id = serializers.UUIDField(read_only=True)
    reported_by_id = serializers.UUIDField(read_only=True)
    reported_user_id = serializers.UUIDField(read_only=True)
    reported_message_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "chat_id",
            "reported_by_id",
            "reported_user_id",
            "category",
            "description",
            "reported_message_id",
            "status",
            "admin_notes",
            "resolution_action",
            "is_false_report",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields


class AdminMessageSerializer(serializers.Serializer):
    """Chat evidence for moderation (raw content, including deleted)."""

    id = serializers.UUIDField()
    sender_id = serializers.UUIDField(allow_null=True)
    message_type = serializers.CharField()
    text_content = serializers.CharField()
    media_url = serializers.SerializerMethodField()
    is_deleted = serializers.BooleanField()
    reactions = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_media_url(self, obj: Message) -> str | None:
        if obj.media_url and obj.media_status != MediaStatus.DELETED:
            return resolve_media_url(obj.media_url)
        return None

    def get_reactions(self, obj: Message) -> list[dict]:
        # Admins see reactions as evidence even on deleted messages.
        return reactions_payload(obj, mask_deleted=False)


class ResolveReportSerializer(serializers.Serializer):
    resolution_action = serializers.ChoiceField(choices=ResolutionAction.choices)
    admin_notes = serializers.CharField(required=False, allow_blank=True, default="")
    is_false_report = serializers.BooleanField(required=False, default=False)


class DismissReportSerializer(serializers.Serializer):
    is_false_report = serializers.BooleanField(required=False, default=False)
    admin_notes = serializers.CharField(required=False, allow_blank=True, default="")


class AdminUserSerializer(serializers.ModelSerializer):
    """Full user view for admin management."""

    profile_photo_url = serializers.SerializerMethodField()
    age = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "college_email",
            "full_name",
            "profile_photo_url",
            "gender",
            "intent",
            "gender_preferences",
            "date_of_birth",
            "age",
            "age_preference_enabled",
            "age_preference_min",
            "age_preference_max",
            "verification_status",
            "account_status",
            "onboarding_completed_at",
            "verified_at",
            "last_active_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_profile_photo_url(self, obj: User) -> str:
        return resolve_media_url(obj.profile_photo_url)


class FeatureFlagSerializer(serializers.ModelSerializer):
    updated_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = FeatureFlag
        fields = ["id", "key", "value", "description", "updated_by_id", "updated_at"]
        read_only_fields = fields


class AppConfigSerializer(serializers.ModelSerializer):
    updated_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = AppConfig
        fields = ["id", "key", "value", "description", "updated_by_id", "updated_at"]
        read_only_fields = fields


class SetValueSerializer(serializers.Serializer):
    """Body for updating a feature flag or app-config entry."""

    value = serializers.JSONField()
    description = serializers.CharField(required=False, allow_blank=True)


class AdminCollegeSerializer(serializers.ModelSerializer):
    """College view for admin management, with live launch state + member count."""

    is_launched = serializers.BooleanField(read_only=True)
    user_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = College
        fields = [
            "id",
            "code",
            "name",
            "allowed_email_domains",
            "launch_date",
            "is_active",
            "is_launched",
            "user_count",
            "created_at",
        ]
        read_only_fields = ["id", "is_launched", "user_count", "created_at"]


class AdminCollegeUpdateSerializer(serializers.Serializer):
    """Editable college fields for PATCH /admin/colleges/{id}."""

    name = serializers.CharField(max_length=150, required=False)
    launch_date = serializers.DateTimeField(required=False, allow_null=True)
    allowed_email_domains = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True,
    )
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("No editable fields were provided.")
        return attrs


class AdminLeakEventSerializer(serializers.ModelSerializer):
    """Veil leak event with applicant context, for the T&S view. Includes the raw
    leaked text (admin-only) per the temporary raw-logging policy."""

    user_id = serializers.UUIDField(read_only=True)
    chat_id = serializers.UUIDField(read_only=True, allow_null=True)
    user_email = serializers.CharField(source="user.college_email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = LeakEvent
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "chat_id",
            "category",
            "severity",
            "action",
            "mode",
            "source",
            "rule_version",
            "detectors",
            "matched_span",
            "raw_message",
            "created_at",
        ]
        read_only_fields = fields


class AdminSuspicionEventSerializer(serializers.ModelSerializer):
    """Second-hand Veil suspicion event with applicant context, for the T&S view."""

    user_id = serializers.UUIDField(read_only=True)
    chat_id = serializers.UUIDField(read_only=True, allow_null=True)
    user_email = serializers.CharField(source="user.college_email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = SuspicionEvent
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "chat_id",
            "top_signal",
            "score",
            "signals",
            "rule_version",
            "raw_message",
            "created_at",
        ]
        read_only_fields = fields


class SuspicionReviewSerializer(serializers.Serializer):
    """Admin assessment of a user's accumulated suspicion."""

    status = serializers.ChoiceField(choices=SuspicionReviewStatus.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AdminProfanityEventSerializer(serializers.ModelSerializer):
    """Muffle profanity event with applicant context, for the T&S view."""

    user_id = serializers.UUIDField(read_only=True)
    chat_id = serializers.UUIDField(read_only=True, allow_null=True)
    user_email = serializers.CharField(source="user.college_email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = ProfanityEvent
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "chat_id",
            "tier",
            "mode",
            "rule_version",
            "words",
            "raw_message",
            "masked_message",
            "created_at",
        ]
        read_only_fields = fields


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_type",
            "actor_id",
            "action",
            "entity_type",
            "entity_id",
            "metadata",
            "request_id",
            "created_at",
        ]
        read_only_fields = fields


_PURPOSE_LABEL = {
    "REVEAL": "reveal",
    "SAFE_REVEAL": "safe reveal",
    "CHAT_EXTENSION": "chat extension",
}


class CoinLedgerAdminSerializer(serializers.Serializer):
    """One coin-ledger row for the admin per-user coin tab. Carries a ready-to-show
    ``label`` and the running ``balance_after`` so the frontend renders a timeline
    with no math of its own, plus pack provenance via the linked Payment."""

    id = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    direction = serializers.SerializerMethodField()
    delta = serializers.IntegerField(read_only=True)
    balance_after = serializers.IntegerField(read_only=True)
    reason = serializers.CharField(read_only=True)
    purpose = serializers.CharField(read_only=True)
    chat_id = serializers.UUIDField(read_only=True, allow_null=True)
    note = serializers.CharField(read_only=True)
    label = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()

    def get_direction(self, obj) -> str:
        return "credit" if obj.delta >= 0 else "spend"

    def get_payment(self, obj):
        p = getattr(obj, "payment", None)
        if p is None:
            return None
        meta = p.metadata or {}
        return {
            "amount_in_paise": p.amount_in_paise,
            "product_id": meta.get("product_id"),
            "coins": meta.get("coins"),
            "provider_payment_id": p.provider_payment_id,
            "status": p.status,
        }

    def get_label(self, obj) -> str:
        coins = abs(obj.delta)
        if obj.reason == "BUNDLE_PURCHASE":
            p = getattr(obj, "payment", None)
            sku = (p.metadata or {}).get("product_id") if p else None
            if p and p.amount_in_paise:
                rupees = p.amount_in_paise / 100
                if sku:
                    return f"Bought {coins} coins ({sku}, Rs {rupees:.0f})"
                return f"Bought {coins} coins (Rs {rupees:.0f})"
            return f"Bought {coins} coins"
        if obj.reason == "ACTION_CONSUME":
            return f"Spent {coins} coins on {_PURPOSE_LABEL.get(obj.purpose, 'an action')}"
        if obj.reason == "CANCELLATION_CREDIT":
            act = _PURPOSE_LABEL.get(obj.purpose, "a cancelled action")
            return f"Refunded {coins} coins ({act} cancelled)"
        if obj.reason == "ADMIN_ADJUST":
            verb = "added" if obj.delta >= 0 else "deducted"
            note = f" (note: {obj.note})" if obj.note else ""
            return f"Admin {verb} {coins} coins{note}"
        return f"{obj.delta:+d} coins"
