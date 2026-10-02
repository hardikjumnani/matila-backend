"""
Admin college-management API: list colleges and set their launch date (plus
name / domains / active flag). The launch date is the lever that opens the core
app for a college's verified members. See docs/COLLEGE_LAUNCH_PLAN.md.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.admin_panel.api.base import AdminAPIView
from apps.admin_panel.api.serializers import (
    AdminCollegeSerializer,
    AdminCollegeUpdateSerializer,
)
from apps.colleges.models import College
from apps.colleges.services.college_service import CollegeService
from apps.common.responses import envelope_error


class AdminCollegeListView(AdminAPIView):
    """GET /admin/colleges — all colleges with launch state and member counts."""

    @extend_schema(responses=AdminCollegeSerializer(many=True))
    def get(self, request: Request) -> Response:
        colleges = CollegeService().list_with_counts()
        return Response(AdminCollegeSerializer(colleges, many=True).data)


class AdminCollegeDetailView(AdminAPIView):
    """GET / PATCH /admin/colleges/{id} — view or edit a college's launch date."""

    def _get(self, college_id: str) -> College | None:
        return (
            CollegeService()
            .list_with_counts()
            .filter(id=college_id)
            .first()
        )

    @extend_schema(responses=AdminCollegeSerializer)
    def get(self, request: Request, college_id: str) -> Response:
        college = self._get(college_id)
        if college is None:
            return envelope_error("RESOURCE_NOT_FOUND", "College not found.", 404)
        return Response(AdminCollegeSerializer(college).data)

    @extend_schema(
        request=AdminCollegeUpdateSerializer, responses=AdminCollegeSerializer
    )
    def patch(self, request: Request, college_id: str) -> Response:
        college = College.objects.filter(id=college_id).first()
        if college is None:
            return envelope_error("RESOURCE_NOT_FOUND", "College not found.", 404)
        serializer = AdminCollegeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        CollegeService().update_college(
            college,
            fields=serializer.validated_data,
            admin_id=str(request.user.id),
        )
        # Re-read with the member-count annotation for a consistent response shape.
        college = self._get(college_id)
        return Response(AdminCollegeSerializer(college).data)
