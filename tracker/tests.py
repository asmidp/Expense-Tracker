from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tracker.forms import build_splits_for_expense
from tracker.models import Expense, Group, Settlement, Split
from tracker.services.balances import compute_net_balances, simplify_debts

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pass1234")
        self.bob = User.objects.create_user("bob", password="pass1234")
        self.carl = User.objects.create_user("carl", password="pass1234")
        self.eve = User.objects.create_user("eve", password="pass1234")
        self.group = Group.objects.create(name="Trip", created_by=self.alice)
        self.group.members.add(self.alice, self.bob, self.carl)
        self.members = self.group.members.order_by("username")

    def expense(self, amount="90.00", payer=None):
        return Expense(group=self.group, description="x", amount=D(amount), payer=payer or self.alice)


class SplitLogicTests(Base):
    def test_equal_split_rounding_goes_to_payer(self):
        splits = build_splits_for_expense(expense=self.expense("100.00"), members=self.members,
                                          split_type="EQUAL", posted_data={})
        amounts = {s.user.username: s.amount for s in splits}
        self.assertEqual(amounts, {"alice": D("33.34"), "bob": D("33.33"), "carl": D("33.33")})

    def test_equal_split_subset_of_members(self):
        data = {f"split_include_{self.alice.id}": "1", f"split_include_{self.bob.id}": "1"}
        splits = build_splits_for_expense(expense=self.expense("90.00"), members=self.members,
                                          split_type="EQUAL", posted_data=data)
        self.assertEqual(sorted(s.user.username for s in splits), ["alice", "bob"])
        self.assertTrue(all(s.amount == D("45.00") for s in splits))

    def test_exact_split_must_match_total(self):
        data = {f"split_exact_{u.id}": "30" for u in self.members}
        data[f"split_exact_{self.carl.id}"] = "20"
        with self.assertRaises(forms.ValidationError):
            build_splits_for_expense(expense=self.expense("90.00"), members=self.members,
                                     split_type="EXACT", posted_data=data)

    def test_percent_split(self):
        data = {f"split_percent_{self.alice.id}": "50", f"split_percent_{self.bob.id}": "25",
                f"split_percent_{self.carl.id}": "25"}
        splits = build_splits_for_expense(expense=self.expense("200.00"), members=self.members,
                                          split_type="PERCENT", posted_data=data)
        self.assertEqual({s.user.username: s.amount for s in splits},
                         {"alice": D("100.00"), "bob": D("50.00"), "carl": D("50.00")})

    def test_percent_must_total_100(self):
        data = {f"split_percent_{u.id}": "30" for u in self.members}
        with self.assertRaises(forms.ValidationError):
            build_splits_for_expense(expense=self.expense(), members=self.members,
                                     split_type="PERCENT", posted_data=data)


class BalanceTests(Base):
    def _add(self, amount, payer, shares):
        ex = Expense.objects.create(group=self.group, description="e", amount=D(amount), payer=payer)
        for u, a in shares.items():
            Split.objects.create(expense=ex, user=u, amount=D(a))

    def test_balances_and_settlement(self):
        self._add("90.00", self.alice, {self.alice: "30", self.bob: "30", self.carl: "30"})
        Settlement.objects.create(group=self.group, payer=self.bob, receiver=self.alice, amount=D("30"))
        net = compute_net_balances(group=self.group)
        self.assertEqual(net[self.alice], D("30.00"))
        self.assertEqual(net[self.bob], D("0.00"))
        self.assertEqual(net[self.carl], D("-30.00"))
        self.assertEqual(sum(net.values()), D("0.00"))

    def test_simplify_debts(self):
        self._add("90.00", self.alice, {self.alice: "30", self.bob: "30", self.carl: "30"})
        self._add("60.00", self.bob, {self.alice: "20", self.bob: "20", self.carl: "20"})
        transfers = simplify_debts(compute_net_balances(group=self.group))
        # alice +40, bob +10, carl -50 -> carl pays alice 40 and bob 10
        got = {(t.debtor.username, t.creditor.username): t.amount for t in transfers}
        self.assertEqual(got, {("carl", "alice"): D("40.00"), ("carl", "bob"): D("10.00")})


class ViewTests(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="alice", password="pass1234")

    def test_signup_duplicate_username_shows_error(self):
        self.client.logout()
        r = self.client.post(reverse("signup"), {"username": "alice", "password1": "Xyz!12345abc",
                                                 "password2": "Xyz!12345abc"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already exists")

    def test_bad_login_shows_error(self):
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
        self.assertContains(r, "correct username and password")

    def test_non_member_gets_404(self):
        self.client.login(username="eve", password="pass1234")
        self.assertEqual(self.client.get(reverse("group_dashboard", args=[self.group.id])).status_code, 404)

    def test_pages_render(self):
        for name, args in [("home", []), ("groups_list", []), ("group_create", []),
                           ("group_dashboard", [self.group.id]), ("group_edit", [self.group.id]),
                           ("expense_create", [self.group.id]), ("settle_create", [self.group.id])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_create_edit_delete_expense(self):
        url = reverse("expense_create", args=[self.group.id])
        r = self.client.post(url, {"description": "Dinner", "amount": "300", "date": "2026-01-10",
                                   "payer": self.alice.id, "split_type": "EQUAL"})
        self.assertRedirects(r, reverse("group_dashboard", args=[self.group.id]))
        ex = Expense.objects.get(description="Dinner")
        self.assertEqual(ex.split_set.count(), 3)

        # invalid exact split re-renders with error instead of crashing
        r = self.client.post(reverse("expense_edit", args=[self.group.id, ex.id]), {
            "description": "Dinner", "amount": "300", "date": "2026-01-10", "payer": self.alice.id,
            "split_type": "EXACT", f"split_exact_{self.alice.id}": "100",
            f"split_exact_{self.bob.id}": "100", f"split_exact_{self.carl.id}": "50"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "add up to")
        self.assertEqual(ex.split_set.count(), 3)  # unchanged

        r = self.client.get(reverse("group_dashboard", args=[self.group.id]))
        self.assertContains(r, "Who owes whom")
        self.client.post(reverse("expense_delete", args=[self.group.id, ex.id]))
        self.assertFalse(Expense.objects.filter(id=ex.id).exists())

    def test_settlement_crud_and_validation(self):
        url = reverse("settle_create", args=[self.group.id])
        r = self.client.post(url, {"payer": self.alice.id, "receiver": self.alice.id, "amount": "10",
                                   "date": "2026-01-01"})
        self.assertContains(r, "must be different")
        self.client.post(url, {"payer": self.bob.id, "receiver": self.alice.id, "amount": "10",
                               "date": "2026-01-01"})
        st = Settlement.objects.get()
        self.client.post(reverse("settle_edit", args=[self.group.id, st.id]),
                         {"payer": self.bob.id, "receiver": self.alice.id, "amount": "15", "date": "2026-01-01"})
        st.refresh_from_db()
        self.assertEqual(st.amount, D("15.00"))
        self.client.post(reverse("settle_delete", args=[self.group.id, st.id]))
        self.assertFalse(Settlement.objects.exists())

    def test_cannot_leave_with_balance(self):
        ex = Expense.objects.create(group=self.group, description="e", amount=D("30"), payer=self.bob)
        Split.objects.create(expense=ex, user=self.alice, amount=D("30"))
        self.client.post(reverse("leave_group", args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.alice.id).exists())

    def test_group_create_includes_creator(self):
        self.client.post(reverse("group_create"), {"name": "Flat", "members": [self.bob.id]})
        g = Group.objects.get(name="Flat")
        self.assertEqual(set(g.members.values_list("username", flat=True)), {"alice", "bob"})

    def test_chart_data_is_escaped(self):
        from tracker.models import Category
        cat = Category.objects.create(name="</script><b>x")
        Expense.objects.create(group=self.group, description="e", amount=D("5"), payer=self.alice, category=cat)
        r = self.client.get(reverse("group_dashboard", args=[self.group.id]))
        self.assertNotContains(r, "</script><b>x")
