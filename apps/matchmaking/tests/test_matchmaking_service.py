"""Tests for MatchmakingService (notifications mocked; real ChatService)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.chats.services.chat_service import ChatService
from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


def _eligible(gender: str, intent: str, prefs: list[str]) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent=intent,
        gender_preferences=prefs,
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


class MatchmakingServiceTests(TestCase):
    def setUp(self) -> None:
        self.notifications = mock.MagicMock()
        chat_service = ChatService(notification_service=mock.MagicMock())
        self.service = MatchmakingService(
            chat_service=chat_service, notification_service=self.notifications
        )

    def test_unverified_user_cannot_join(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        user.verification_status = VerificationStatus.PENDING
        user.save(update_fields=["verification_status"])
        self.assertEqual(self.service.join(user).error_code, "VERIFICATION_REQUIRED")

    def test_join_without_partner_queues(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        result = self.service.join(user)
        self.assertTrue(result.success)
        self.assertFalse(result.data.matched)
        self.assertEqual(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).count(),
            1,
        )

    def test_join_is_idempotent(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        self.service.join(user)
        self.assertEqual(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).count(),
            1,
        )

    def test_compatible_users_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        result = self.service.join(b)
        self.assertTrue(result.data.matched)
        self.assertIsNotNone(result.data.chat)
        # Both queue entries removed on match.
        self.assertEqual(
            MatchQueue.objects.filter(status=MatchQueueStatus.SEARCHING).count(), 0
        )
        # Both users notified.
        self.assertEqual(self.notifications.create_notification.call_count, 2)

    def test_incompatible_gender_preference_does_not_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.MALE])  # wants MALE
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        result = self.service.join(b)
        self.assertFalse(result.data.matched)

    def test_different_intent_does_not_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.CASUAL, [Gender.MALE])
        self.service.join(a)
        self.assertFalse(self.service.join(b).data.matched)

    def test_empty_preferences_match_any_gender(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [])
        self.service.join(a)
        self.assertTrue(self.service.join(b).data.matched)

    # -- Age-preference hard filter (relationship intent) -------------------

    @staticmethod
    def _dob_for_age(years: int):
        from datetime import date

        today = timezone.now().date()
        # Born Jan 1 => this year's birthday has passed => exact age == years.
        return date(today.year - years, 1, 1)

    def _set_age(self, user: User, age: int) -> None:
        user.date_of_birth = self._dob_for_age(age)
        user.save(update_fields=["date_of_birth"])

    def _set_age_pref(self, user: User, lo: int, hi: int) -> None:
        user.age_preference_enabled = True
        user.age_preference_min = lo
        user.age_preference_max = hi
        user.save(
            update_fields=[
                "age_preference_enabled",
                "age_preference_min",
                "age_preference_max",
            ]
        )

    def test_age_in_range_matches(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age(b, 18)
        self._set_age_pref(a, 18, 19)  # A wants 18-19; B is 18 -> in range
        self.service.join(a)
        self.assertTrue(self.service.join(b).data.matched)

    def test_age_above_range_excluded(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age(b, 20)
        self._set_age_pref(a, 18, 19)  # B is 20 -> out of range
        self.service.join(a)
        self.assertFalse(self.service.join(b).data.matched)

    def test_age_preference_off_imposes_no_restriction(self) -> None:
        # A has no preference (default off); B is any age -> A does not filter.
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age(b, 29)
        self.service.join(a)
        self.assertTrue(self.service.join(b).data.matched)

    def test_other_sides_filter_still_applies(self) -> None:
        # A has no restriction, but B requires 18-19 and A is 25 -> B's filter blocks.
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age(b, 18)
        self._set_age_pref(b, 18, 19)
        self.service.join(a)
        self.assertFalse(self.service.join(b).data.matched)

    def test_unknown_age_excluded_by_active_filter(self) -> None:
        # B has no DOB; A's active filter cannot be satisfied by an unknown age.
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age_pref(a, 18, 30)
        # b.date_of_birth stays None
        self.service.join(a)
        self.assertFalse(self.service.join(b).data.matched)

    def test_age_filter_ignored_for_non_relationship(self) -> None:
        # Age preference is relationship-only: a CASUAL user with it enabled still
        # matches regardless of age.
        a = _eligible(Gender.MALE, Intent.CASUAL, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.CASUAL, [Gender.MALE])
        self._set_age(a, 25)
        self._set_age(b, 29)
        self._set_age_pref(a, 18, 19)  # would exclude B at 29 if applied
        self.service.join(a)
        self.assertTrue(self.service.join(b).data.matched)

    # -- No re-matching a previous partner ----------------------------------

    def _match_then_end(self, a: User, b: User) -> Chat:
        """Match a and b into a chat, then end it so the slot is freed."""
        self.service.join(a)
        self.service.join(b)
        chat = Chat.objects.filter(participants__user=a).first()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.ENDED)
        return chat

    def test_does_not_rematch_previous_partner(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._match_then_end(a, b)  # they have shared a chat before
        # Both requeue; they are each other's only candidate -> no match.
        self.service.join(b)
        result = self.service.join(a)
        self.assertFalse(result.data.matched)
        self.assertEqual(
            MatchQueue.objects.filter(status=MatchQueueStatus.SEARCHING).count(), 2
        )

    def test_matches_new_partner_not_past_partner(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        past = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self._match_then_end(a, past)  # a and past chatted before
        # A fresh compatible user is also waiting alongside the past partner.
        fresh = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(past)
        self.service.join(fresh)
        result = self.service.join(a)
        self.assertTrue(result.data.matched)
        partner_ids = set(
            ChatParticipant.objects.filter(chat=result.data.chat)
            .exclude(user=a)
            .values_list("user_id", flat=True)
        )
        self.assertEqual(partner_ids, {fresh.id})  # fresh, never the past partner

    def test_lobby_stats_excludes_past_partner(self) -> None:
        me = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        online = {str(me.id)}
        for _ in range(9):  # 9 fresh compatible users
            online.add(
                str(_eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE]).id)
            )
        # A 10th compatible user, but already matched with me before -> excluded.
        past = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        ChatService(notification_service=mock.MagicMock()).create_chat(me, past)
        Chat.objects.filter(participants__user=me).update(status=ChatStatus.ENDED)
        online.add(str(past.id))

        presence = mock.MagicMock()
        presence.online_ids.return_value = set(online)
        presence.online_count.return_value = len(online)
        svc = MatchmakingService(
            chat_service=ChatService(notification_service=mock.MagicMock()),
            notification_service=mock.MagicMock(),
            presence_service=presence,
        )
        stats = svc.get_lobby_stats(me)
        # 9 fresh count; the past partner is excluded, so it stays 0+ not 10+.
        self.assertEqual(stats["compatible_online"], {"floor": 0, "label": "0+"})

    def test_cannot_join_with_active_chat(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        self.service.join(b)  # a and b now in a chat
        self.assertEqual(self.service.join(a).error_code, "CONFLICT")

    def _matched_pair_chat(self):
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        self.service.join(b)
        chat = Chat.objects.filter(participants__user=a).first()
        return a, chat

    def test_revealed_chat_frees_the_match_slot(self) -> None:
        # Rule (AI_BRIDGE [00055]): a REVEALED chat must NOT block a new match.
        a, chat = self._matched_pair_chat()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.REVEALED)
        self.assertTrue(self.service.join(a).success)

    def test_ended_chat_frees_the_match_slot(self) -> None:
        a, chat = self._matched_pair_chat()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.ENDED)
        self.assertTrue(self.service.join(a).success)

    def test_expired_chat_still_blocks_match(self) -> None:
        # EXPIRED means a decision round is still pending -> blocks a new match.
        a, chat = self._matched_pair_chat()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.EXPIRED)
        self.assertEqual(self.service.join(a).error_code, "CONFLICT")

    def test_status_revealed_chat_is_not_matched(self) -> None:
        # [00056]: a revealed chat must not read as MATCHED in matchmaking status.
        a, chat = self._matched_pair_chat()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.REVEALED)
        self.assertEqual(self.service.get_status(a)["state"], "IDLE")

    def test_status_active_chat_is_matched(self) -> None:
        a, chat = self._matched_pair_chat()
        status = self.service.get_status(a)
        self.assertEqual(status["state"], "MATCHED")
        self.assertEqual(status["chat_id"], str(chat.id))

    def test_status_expired_chat_is_matched(self) -> None:
        a, chat = self._matched_pair_chat()
        Chat.objects.filter(id=chat.id).update(status=ChatStatus.EXPIRED)
        self.assertEqual(self.service.get_status(a)["state"], "MATCHED")

    def test_leave_cancels_entry(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        self.service.leave(user)
        self.assertFalse(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).exists()
        )

    def test_status_transitions(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.assertEqual(self.service.get_status(user)["state"], "IDLE")
        self.service.join(user)
        self.assertEqual(self.service.get_status(user)["state"], "SEARCHING")

    def test_heartbeat_without_entry_fails(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.assertEqual(self.service.heartbeat(user).error_code, "RESOURCE_NOT_FOUND")

    def test_cleanup_stale_times_out_entries(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        MatchQueue.objects.filter(user=user).update(
            last_heartbeat_at=timezone.now() - timedelta(minutes=30)
        )
        removed = self.service.cleanup_stale(timeout_seconds=300)
        self.assertEqual(removed, 1)
        entry = MatchQueue.objects.get(user=user)
        self.assertEqual(entry.status, MatchQueueStatus.TIMEOUT)

    def test_plus_range_buckets(self) -> None:
        pr = self.service._plus_range
        self.assertEqual(pr(0), {"floor": 0, "label": "0+"})
        self.assertEqual(pr(9), {"floor": 0, "label": "0+"})
        self.assertEqual(pr(10), {"floor": 10, "label": "10+"})
        self.assertEqual(pr(27), {"floor": 20, "label": "20+"})

    def test_intent_stats_all_intents(self) -> None:
        for _ in range(10):
            _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        _eligible(Gender.FEMALE, Intent.FRIENDSHIP, [Gender.MALE])
        stats = self.service.get_intent_stats()
        self.assertEqual(set(stats), {"RELATIONSHIP", "FRIENDSHIP", "CASUAL"})
        self.assertEqual(stats["RELATIONSHIP"], {"floor": 10, "label": "10+"})
        self.assertEqual(stats["FRIENDSHIP"], {"floor": 0, "label": "0+"})
        self.assertEqual(stats["CASUAL"], {"floor": 0, "label": "0+"})

    def test_lobby_stats_compatible_filtering(self) -> None:
        me = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        ids = {str(me.id)}
        # 10 compatible: female / relationship / accepts males.
        for _ in range(10):
            ids.add(str(_eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE]).id))
        # 10 incompatible (must all be excluded, else the count crosses to 20+):
        for _ in range(4):  # wrong intent
            ids.add(str(_eligible(Gender.FEMALE, Intent.CASUAL, [Gender.MALE]).id))
        for _ in range(3):  # wrong gender (I want FEMALE)
            ids.add(str(_eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.MALE]).id))
        for _ in range(3):  # she doesn't accept males
            ids.add(str(_eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.FEMALE]).id))
        # a compatible user who is BUSY in an active chat -> excluded.
        busy = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        partner = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        ChatService(notification_service=mock.MagicMock()).create_chat(busy, partner)
        ids.add(str(busy.id))

        presence = mock.MagicMock()
        presence.online_ids.return_value = set(ids)
        presence.online_count.return_value = len(ids)
        svc = MatchmakingService(
            chat_service=ChatService(notification_service=mock.MagicMock()),
            notification_service=mock.MagicMock(),
            presence_service=presence,
        )
        stats = svc.get_lobby_stats(me)
        # Exactly the 10 compatible; the 10 incompatible would push it to 20+ if leaked.
        self.assertEqual(stats["compatible_online"], {"floor": 10, "label": "10+"})
        self.assertEqual(stats["total_online"]["floor"], (len(ids) // 10) * 10)
