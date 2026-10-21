from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Group(models.Model):
    name = models.CharField(max_length=100)
    members = models.ManyToManyField(User, related_name="user_groups")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_groups"
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class Expense(models.Model):
    class SplitType(models.TextChoices):
        EQUAL = "EQUAL", "Equal"
        EXACT = "EXACT", "Exact amounts"
        PERCENT = "PERCENT", "Percentages"

    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payer = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.localdate)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    split_type = models.CharField(max_length=10, choices=SplitType.choices, default=SplitType.EQUAL)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.description


class Split(models.Model):
    """One participant's share of an expense (who owes what)."""

    expense = models.ForeignKey(Expense, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # For percent splits we store the percent here (0-100). Null for equal/exact.
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.user} owes {self.amount} for {self.expense}"


class Settlement(models.Model):
    """A repayment: `payer` paid `receiver` back."""

    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    payer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payer")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="receiver")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.payer} -> {self.receiver}: {self.amount}"
