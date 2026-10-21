from __future__ import annotations

from django.http import Http404

from tracker.models import Expense, Group, Settlement


def get_group_for_user_or_404(*, group_id: int, user) -> Group:
    try:
        return Group.objects.get(id=group_id, members=user)
    except Group.DoesNotExist as exc:
        raise Http404("Group not found") from exc


def get_expense_for_user_or_404(*, expense_id: int, user, group: Group | None = None) -> Expense:
    qs = Expense.objects.select_related("group", "payer", "category").filter(group__members=user)
    if group is not None:
        qs = qs.filter(group=group)
    try:
        return qs.get(id=expense_id)
    except Expense.DoesNotExist as exc:
        raise Http404("Expense not found") from exc


def get_settlement_for_user_or_404(*, settlement_id: int, user, group: Group) -> Settlement:
    try:
        return Settlement.objects.select_related("payer", "receiver").get(
            id=settlement_id, group=group, group__members=user
        )
    except Settlement.DoesNotExist as exc:
        raise Http404("Settlement not found") from exc
