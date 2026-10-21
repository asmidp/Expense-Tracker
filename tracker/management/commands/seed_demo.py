from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tracker.forms import build_splits_for_expense
from tracker.models import Category, Expense, Group, Settlement, Split
from tracker.views import DEFAULT_CATEGORIES

PASSWORD = "pass1234"


class Command(BaseCommand):
    help = "Seed demo users, two groups, and sample expenses using every split type."

    @transaction.atomic
    def handle(self, *args, **options):
        for name in DEFAULT_CATEGORIES:
            Category.objects.get_or_create(name=name)
        cat = {c.name: c for c in Category.objects.all()}

        users = {}
        for name in ("alice", "bob", "charlie", "diya"):
            u, created = User.objects.get_or_create(username=name, defaults={"email": f"{name}@example.com"})
            if created or not u.has_usable_password():
                u.set_password(PASSWORD)
                u.save()
            users[name] = u
        a, b, c, d = users["alice"], users["bob"], users["charlie"], users["diya"]

        today = timezone.localdate()
        created = 0

        def add(group, desc, amount, payer, category, days_ago, split_type="EQUAL", data=None):
            nonlocal created
            exp = Expense(
                group=group, description=desc, amount=Decimal(amount), payer=payer,
                category=cat[category], date=today - timedelta(days=days_ago), split_type=split_type,
            )
            splits = build_splits_for_expense(
                expense=exp, members=group.members.order_by("username"),
                split_type=split_type, posted_data=data or {},
            )
            exp.save()
            for s in splits:
                s.expense = exp
            Split.objects.bulk_create(splits)
            created += 1

        trip, new_trip = Group.objects.get_or_create(name="Goa Trip", defaults={"created_by": a})
        trip.members.add(a, b, c)
        if new_trip or not trip.expense_set.exists():
            add(trip, "Hotel (3 nights)", "12000.00", a, "Travel", 70)
            add(trip, "Flight tickets", "15600.00", b, "Travel", 72)
            add(trip, "Seafood dinner", "3450.00", c, "Food", 69)
            add(trip, "Scooter rental", "1800.00", a, "Transport", 68, "EXACT",
                {f"split_exact_{a.id}": "600", f"split_exact_{b.id}": "600", f"split_exact_{c.id}": "600"})
            add(trip, "Beach shack drinks", "2400.00", b, "Entertainment", 68, "PERCENT",
                {f"split_percent_{a.id}": "25", f"split_percent_{b.id}": "50", f"split_percent_{c.id}": "25"})
            add(trip, "Souvenirs", "900.00", c, "Shopping", 67, "EQUAL",
                {f"split_include_{a.id}": "1", f"split_include_{c.id}": "1"})
            Settlement.objects.create(group=trip, payer=c, receiver=a, amount=Decimal("2000.00"),
                                      date=today - timedelta(days=40), note="UPI")

        flat, new_flat = Group.objects.get_or_create(name="Flat 402", defaults={"created_by": a})
        flat.members.add(a, d)
        if new_flat or not flat.expense_set.exists():
            for m in range(3):
                add(flat, "Rent", "24000.00", a, "Rent", 5 + 30 * m)
                add(flat, "Electricity bill", str(1400 + 150 * m) + ".00", d, "Utilities", 10 + 30 * m)
                add(flat, "Groceries", str(3200 + 400 * m) + ".00", d, "Groceries", 3 + 30 * m)
            add(flat, "Wi-Fi", "999.00", a, "Utilities", 12)

        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(f"Users (password '{PASSWORD}'): alice, bob, charlie, diya")
        self.stdout.write("Groups: Goa Trip (alice, bob, charlie), Flat 402 (alice, diya)")
        self.stdout.write(f"Expenses created this run: {created}")
