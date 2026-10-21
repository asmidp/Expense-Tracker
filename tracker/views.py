from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from tracker.forms import (
    ExpenseForm,
    GroupForm,
    LoginForm,
    SettlementForm,
    SignupForm,
    build_splits_for_expense,
)
from tracker.models import Category, Expense, Group, Settlement, Split
from tracker.services.authz import (
    get_expense_for_user_or_404,
    get_group_for_user_or_404,
    get_settlement_for_user_or_404,
)
from tracker.services.balances import (
    compute_net_balances,
    paid_vs_share,
    simplify_debts,
    user_summary,
)

DEFAULT_CATEGORIES = [
    "Food", "Groceries", "Transport", "Travel", "Rent", "Utilities",
    "Entertainment", "Shopping", "Health", "Other",
]


def _ensure_default_categories():
    for name in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(name=name)


# ================================================================ auth


def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = SignupForm(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome, {user.username}!")
        return redirect("home")
    return render(request, "tracker/signup.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get("next")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("home")
    return render(request, "tracker/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "Logged out.")
    return redirect("login")


# ================================================================ home / groups


@login_required
def home(request):
    """Personal dashboard: balances across all groups + your spending analytics."""
    summary = user_summary(user=request.user)
    my_splits = Split.objects.filter(user=request.user, expense__group__members=request.user)

    by_category = (
        my_splits.values("expense__category__name").annotate(total=Sum("amount")).order_by("-total")
    )
    by_month = (
        my_splits.annotate(month=TruncMonth("expense__date"))
        .values("month").annotate(total=Sum("amount")).order_by("month")
    )
    recent = (
        Expense.objects.filter(group__members=request.user)
        .select_related("group", "payer", "category")
        .order_by("-date", "-id")[:8]
    )
    chart = {
        "catLabels": [r["expense__category__name"] or "Uncategorized" for r in by_category],
        "catValues": [float(r["total"]) for r in by_category],
        "monthLabels": [r["month"].strftime("%b %Y") for r in by_month],
        "monthValues": [float(r["total"]) for r in by_month],
    }
    return render(request, "tracker/home.html", {
        "summary": summary,
        "my_total_share": my_splits.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "recent": recent,
        "chart": chart,
        "has_data": bool(chart["catValues"]),
    })


@login_required
def groups_list(request):
    groups = (
        Group.objects.filter(members=request.user)
        .annotate(member_count=Count("members", distinct=True))
        .order_by("name")
    )
    totals = dict(
        Expense.objects.filter(group__in=groups).values_list("group").annotate(t=Sum("amount"))
    )
    rows = []
    for g in groups:
        bal = compute_net_balances(group=g).get(request.user, Decimal("0.00"))
        rows.append({"group": g, "balance": bal, "total": totals.get(g.id, Decimal("0.00"))})
    return render(request, "tracker/groups_list.html", {"rows": rows})


@login_required
def group_create(request):
    form = GroupForm(request_user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.created_by = request.user
        group.save()
        group.members.set(list(form.cleaned_data["members"]) + [request.user])
        messages.success(request, "Group created.")
        return redirect("group_dashboard", group_id=group.id)
    return render(request, "tracker/group_form.html", {"form": form})


@login_required
@transaction.atomic
def group_edit(request, group_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    form = GroupForm(request_user=request.user, instance=group, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        net = compute_net_balances(group=group)
        keep = set(form.cleaned_data["members"]) | {request.user}
        blocked = [u.username for u in group.members.all() if u not in keep and net.get(u, 0) != 0]
        if blocked:
            form.add_error(
                "members",
                f"Can't remove {', '.join(blocked)}: they still have an unsettled balance.",
            )
        else:
            form.save()
            messages.success(request, "Group updated.")
            return redirect("group_dashboard", group_id=group.id)
    return render(request, "tracker/group_form.html", {"form": form, "group": group, "is_edit": True})


@login_required
def group_dashboard(request, group_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    group_expenses = Expense.objects.filter(group=group)

    category_filter = request.GET.get("category", "")
    listed = group_expenses.select_related("payer", "category").prefetch_related("split_set__user")
    if category_filter == "none":
        listed = listed.filter(category__isnull=True)
    elif category_filter:
        listed = listed.filter(category__name=category_filter)
    listed = listed.order_by("-date", "-id")

    settlements = (
        Settlement.objects.filter(group=group).select_related("payer", "receiver").order_by("-date", "-id")
    )

    net_by_user = compute_net_balances(group=group)
    balances = sorted(net_by_user.items(), key=lambda kv: kv[1], reverse=True)
    transfers = simplify_debts(net_by_user)
    pvs = paid_vs_share(group=group)

    category_totals = (
        group_expenses.values("category__name").annotate(total=Sum("amount")).order_by("-total")
    )
    monthly_totals = (
        group_expenses.annotate(month=TruncMonth("date"))
        .values("month").annotate(total=Sum("amount")).order_by("month")
    )
    trend_totals = group_expenses.values("date").annotate(total=Sum("amount")).order_by("date")

    chart = {
        "labels": [i["category__name"] or "Uncategorized" for i in category_totals],
        "values": [float(i["total"]) for i in category_totals],
        "monthLabels": [i["month"].strftime("%b %Y") for i in monthly_totals],
        "monthValues": [float(i["total"]) for i in monthly_totals],
        "trendLabels": [i["date"].strftime("%d %b") for i in trend_totals],
        "trendValues": [float(i["total"]) for i in trend_totals],
        "memberLabels": [r["user"].username for r in pvs],
        "memberPaid": [float(r["paid"]) for r in pvs],
        "memberShare": [float(r["share"]) for r in pvs],
    }
    total_spend = group_expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return render(request, "tracker/group_dashboard.html", {
        "group": group,
        "members": group.members.order_by("username"),
        "expenses": listed,
        "expense_count": group_expenses.count(),
        "settlements": settlements,
        "balances": balances,
        "my_balance": net_by_user.get(request.user, Decimal("0.00")),
        "transfers": transfers,
        "total_spend": total_spend,
        "categories": [i["category__name"] for i in category_totals if i["category__name"]],
        "has_uncategorized": any(i["category__name"] is None for i in category_totals),
        "category_filter": category_filter,
        "chart": chart,
        "has_expense_data": bool(chart["values"]),
    })


@login_required
def leave_group(request, group_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    balance = compute_net_balances(group=group).get(request.user, Decimal("0.00"))
    if request.method == "POST":
        if balance != 0:
            messages.error(request, "Settle your balance before leaving the group.")
            return redirect("group_dashboard", group_id=group.id)
        group.members.remove(request.user)
        if not group.members.exists():
            group.delete()
        messages.success(request, f"You left {group.name}.")
        return redirect("groups_list")
    return render(request, "tracker/leave_group_confirm.html", {"group": group, "balance": balance})


# ================================================================ expenses


def _split_rows(members, *, posted=None, expense: Expense | None = None):
    """Per-member rows for the split table, pre-filled from POST data or an existing expense."""
    existing = {}
    if expense is not None and expense.pk:
        existing = {s.user_id: s for s in expense.split_set.all()}
    any_include = posted is not None and any(k.startswith("split_include_") for k in posted)
    rows = []
    for m in members:
        if posted is not None:
            rows.append({
                "user": m,
                "included": bool(posted.get(f"split_include_{m.id}")) if any_include else True,
                "exact": posted.get(f"split_exact_{m.id}", ""),
                "percent": posted.get(f"split_percent_{m.id}", ""),
            })
        elif existing:
            s = existing.get(m.id)
            rows.append({
                "user": m,
                "included": s is not None,
                "exact": s.amount if s else "",
                "percent": s.percent if (s and s.percent is not None) else "",
            })
        else:
            rows.append({"user": m, "included": True, "exact": "", "percent": ""})
    return rows


def _save_expense(request, *, group: Group, instance: Expense | None):
    members = group.members.all().order_by("username")
    _ensure_default_categories()
    is_edit = instance is not None
    form = ExpenseForm(
        instance=instance, group=group, request_user=request.user, data=request.POST or None
    )

    if request.method == "POST" and form.is_valid():
        expense: Expense = form.save(commit=False)
        expense.group = group
        try:
            splits = build_splits_for_expense(
                expense=expense, members=members, split_type=expense.split_type, posted_data=request.POST
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            with transaction.atomic():
                expense.save()
                Split.objects.filter(expense=expense).delete()
                for s in splits:
                    s.expense = expense
                Split.objects.bulk_create(splits)
            messages.success(request, "Expense updated." if is_edit else "Expense added.")
            return redirect("group_dashboard", group_id=group.id)

    rows = _split_rows(
        members,
        posted=request.POST if request.method == "POST" else None,
        expense=instance,
    )
    return render(request, "tracker/expense_form.html", {
        "group": group, "form": form, "split_rows": rows, "is_edit": is_edit, "expense": instance,
    })


@login_required
def expense_create(request, group_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    return _save_expense(request, group=group, instance=None)


@login_required
def expense_edit(request, group_id: int, expense_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    expense = get_expense_for_user_or_404(expense_id=expense_id, user=request.user, group=group)
    return _save_expense(request, group=group, instance=expense)


@login_required
def expense_delete(request, group_id: int, expense_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    expense = get_expense_for_user_or_404(expense_id=expense_id, user=request.user, group=group)
    if request.method == "POST":
        expense.delete()
        messages.success(request, "Expense deleted.")
        return redirect("group_dashboard", group_id=group.id)
    return render(request, "tracker/confirm_delete.html", {
        "group": group,
        "title": "Delete expense?",
        "body": f"This will remove “{expense.description}” (₹{expense.amount}) and its splits.",
    })


# ================================================================ settlements


@login_required
def settle_create(request, group_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    if request.method == "POST":
        form = SettlementForm(group=group, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Settlement recorded.")
            return redirect("group_dashboard", group_id=group.id)
    else:
        # Prefill from "Settle" buttons on the dashboard: ?payer=&receiver=&amount=
        initial = {"payer": request.user.id}
        for key in ("payer", "receiver", "amount"):
            if request.GET.get(key):
                initial[key] = request.GET[key]
        form = SettlementForm(group=group, initial=initial)
    return render(request, "tracker/settlement_form.html", {"group": group, "form": form})


@login_required
def settle_edit(request, group_id: int, settlement_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    settlement = get_settlement_for_user_or_404(settlement_id=settlement_id, user=request.user, group=group)
    form = SettlementForm(group=group, instance=settlement, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settlement updated.")
        return redirect("group_dashboard", group_id=group.id)
    return render(request, "tracker/settlement_form.html", {"group": group, "form": form, "is_edit": True})


@login_required
def settle_delete(request, group_id: int, settlement_id: int):
    group = get_group_for_user_or_404(group_id=group_id, user=request.user)
    settlement = get_settlement_for_user_or_404(settlement_id=settlement_id, user=request.user, group=group)
    if request.method == "POST":
        settlement.delete()
        messages.success(request, "Settlement deleted.")
        return redirect("group_dashboard", group_id=group.id)
    return render(request, "tracker/confirm_delete.html", {
        "group": group,
        "title": "Delete settlement?",
        "body": f"{settlement.payer.username} → {settlement.receiver.username}, ₹{settlement.amount}. "
                "Balances will be recalculated.",
    })
