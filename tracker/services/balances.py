from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth.models import User

from tracker.models import Expense, Group, Settlement, Split

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def compute_net_balances(*, group: Group) -> dict[User, Decimal]:
    """
    Net balance per user within a group.
    Convention:
      - positive => user is owed money (creditor)
      - negative => user owes money (debtor)
    Current members always appear, even with a zero balance.
    """
    net: dict[User, Decimal] = defaultdict(lambda: ZERO)
    for m in group.members.all():
        net[m] += ZERO

    # Payer is credited the full amount.
    for e in Expense.objects.filter(group=group).select_related("payer"):
        net[e.payer] += e.amount

    # Every participant (including the payer, if they take part) owes their split.
    for s in Split.objects.filter(expense__group=group).select_related("user"):
        net[s.user] -= s.amount

    # Settlement: payer paid receiver back, reducing payer's debt and receiver's credit.
    for st in Settlement.objects.filter(group=group).select_related("payer", "receiver"):
        net[st.payer] += st.amount
        net[st.receiver] -= st.amount

    return {u: amt.quantize(CENT) for u, amt in net.items()}


@dataclass
class Transfer:
    debtor: User
    creditor: User
    amount: Decimal


def simplify_debts(net: dict[User, Decimal]) -> list[Transfer]:
    """
    Turn net balances into a short list of "X pays Y" transfers (greedy:
    the largest debtor pays the largest creditor until everyone is square).
    """
    debtors = sorted([[u, -a] for u, a in net.items() if a < 0], key=lambda x: x[1], reverse=True)
    creditors = sorted([[u, a] for u, a in net.items() if a > 0], key=lambda x: x[1], reverse=True)
    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        pay = min(debtors[i][1], creditors[j][1]).quantize(CENT)
        if pay > 0:
            transfers.append(Transfer(debtor=debtors[i][0], creditor=creditors[j][0], amount=pay))
        debtors[i][1] -= pay
        creditors[j][1] -= pay
        if debtors[i][1] <= 0:
            i += 1
        if creditors[j][1] <= 0:
            j += 1
    return transfers


def paid_vs_share(*, group: Group) -> list[dict]:
    """How much each member paid for expenses vs. their share of them."""
    paid: dict[User, Decimal] = defaultdict(lambda: ZERO)
    share: dict[User, Decimal] = defaultdict(lambda: ZERO)
    for m in group.members.all():
        paid[m] += ZERO
        share[m] += ZERO
    for e in Expense.objects.filter(group=group).select_related("payer"):
        paid[e.payer] += e.amount
    for s in Split.objects.filter(expense__group=group).select_related("user"):
        share[s.user] += s.amount
    users = sorted(set(paid) | set(share), key=lambda u: u.username.lower())
    return [{"user": u, "paid": paid[u], "share": share[u]} for u in users]


def user_summary(*, user: User) -> dict:
    """Totals across every group the user belongs to (for the home dashboard)."""
    rows, owed, owes = [], ZERO, ZERO
    for group in Group.objects.filter(members=user).order_by("name"):
        net = compute_net_balances(group=group)
        bal = net.get(user, ZERO)
        if bal > 0:
            owed += bal
        elif bal < 0:
            owes += -bal
        rows.append({"group": group, "balance": bal})
    return {"rows": rows, "owed": owed, "owes": owes, "net": owed - owes}
