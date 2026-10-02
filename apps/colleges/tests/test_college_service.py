"""Tests for CollegeService: domain resolution and the launch gate."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.colleges.models import College
from apps.colleges.services.college_service import CollegeService, domain_of
from apps.users.models import User


def _college(code: str, domains: list[str], *, launch_offset_days: float | None) -> College:
    launch = (
        None
        if launch_offset_days is None
        else timezone.now() + timedelta(days=launch_offset_days)
    )
    return College.objects.create(
        code=code,
        name=code.title(),
        allowed_email_domains=domains,
        launch_date=launch,
    )


class DomainResolutionTests(TestCase):
    def setUp(self) -> None:
        self.service = CollegeService()
        self.college = _college("BITS", ["bits.ac.in"], launch_offset_days=1)

    def test_domain_of(self) -> None:
        self.assertEqual(domain_of("a@BITS.ac.in"), "bits.ac.in")
        self.assertIsNone(domain_of("not-an-email"))
        self.assertIsNone(domain_of(""))

    def test_resolves_known_domain(self) -> None:
        resolved = self.service.resolve_for_email("Student@BITS.ac.in")
        self.assertEqual(resolved, self.college)

    def test_unknown_domain_returns_none(self) -> None:
        self.assertIsNone(self.service.resolve_for_email("x@unknown.edu"))

    def test_inactive_college_does_not_resolve(self) -> None:
        self.college.is_active = False
        self.college.save(update_fields=["is_active"])
        self.assertIsNone(self.service.resolve_for_email("x@bits.ac.in"))


class LaunchGateTests(TestCase):
    def setUp(self) -> None:
        self.service = CollegeService()

    def _user(self, college: College) -> User:
        return User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@x.edu",
            college=college,
        )

    def test_prelaunch_not_launched(self) -> None:
        user = self._user(_college("A", ["a.edu"], launch_offset_days=5))
        self.assertFalse(self.service.is_user_launched(user))
        info = self.service.launch_info(user)
        self.assertFalse(info["launched"])
        self.assertEqual(info["college"]["code"], "A")
        self.assertFalse(info["college"]["launched"])
        self.assertIsNotNone(info["college"]["launch_date"])

    def test_past_launch_is_launched(self) -> None:
        user = self._user(_college("B", ["b.edu"], launch_offset_days=-1))
        self.assertTrue(self.service.is_user_launched(user))
        self.assertTrue(self.service.launch_info(user)["launched"])

    def test_unscheduled_launch_not_launched(self) -> None:
        user = self._user(_college("C", ["c.edu"], launch_offset_days=None))
        self.assertFalse(self.service.is_user_launched(user))


class UpdateCollegeTests(TestCase):
    def test_update_launch_date_is_audited(self) -> None:
        college = _college("D", ["d.edu"], launch_offset_days=None)
        new_launch = timezone.now() + timedelta(days=2)
        CollegeService().update_college(
            college, fields={"launch_date": new_launch}, admin_id="admin-1"
        )
        college.refresh_from_db()
        self.assertEqual(college.launch_date, new_launch)
        self.assertTrue(
            AuditLog.objects.filter(
                action="college.updated", entity_id=str(college.id)
            ).exists()
        )

    def test_domains_are_lowercased(self) -> None:
        college = _college("E", ["e.edu"], launch_offset_days=None)
        CollegeService().update_college(
            college, fields={"allowed_email_domains": ["Foo.EDU", "BAR.edu"]}
        )
        college.refresh_from_db()
        self.assertEqual(college.allowed_email_domains, ["foo.edu", "bar.edu"])

    def test_unknown_fields_ignored(self) -> None:
        college = _college("F", ["f.edu"], launch_offset_days=None)
        CollegeService().update_college(college, fields={"code": "HACKED"})
        college.refresh_from_db()
        self.assertEqual(college.code, "F")
