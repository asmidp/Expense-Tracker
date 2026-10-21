from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from tracker.models import Category, Expense, Group, Settlement, Split

CENT = Decimal("0.01")


def _style(form: forms.BaseForm) -> None:
    """Add Bootstrap classes to every widget in a form."""
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput, forms.HiddenInput)):
            continue
        css = "form-select" if isinstance(widget, forms.Select) else "form-control"
        widget.attrs["class"] = (widget.attrs.get("class", "") + " " + css).strip()


# ---------------------------------------------------------------- auth


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


# ---------------------------------------------------------------- groups


class GroupForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="You are always a member of groups you create.",
    )

    class Meta:
        model = Group
        fields = ["name", "members"]

    def __init__(self, *args, request_user: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_user = request_user
        self.fields["members"].queryset = User.objects.exclude(id=request_user.id).order_by("username")
        if self.instance.pk:
            self.initial["members"] = list(
                self.instance.members.exclude(id=request_user.id).values_list("id", flat=True)
            )
        _style(self)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Group name is required.")
        return name

    def save(self, commit=True):
        group = super().save(commit=False)
        if commit:
            group.save()
            group.members.set(list(self.cleaned_data["members"]) + [self.request_user])
        return group


# ---------------------------------------------------------------- expenses


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["description", "amount", "date", "category", "payer", "split_type"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "description": forms.TextInput(attrs={"placeholder": "e.g. Dinner at Toit"}),
        }

    def __init__(self, *args, group: Group | None = None, request_user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("name")
        self.fields["category"].empty_label = "Uncategorized"
        if group is not None:
            self.fields["payer"].queryset = group.members.all().order_by("username")
        else:
            self.fields["payer"].queryset = User.objects.none()
        if request_user is not None and not self.instance.pk:
            self.fields["payer"].initial = request_user.id
        _style(self)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount.quantize(CENT)


def _parse_decimal(raw: str, label: str) -> Decimal:
    try:
        value = Decimal(raw).quantize(CENT)
    except (InvalidOperation, ValueError) as exc:
        raise forms.ValidationError(f"Invalid {label}: {raw!r}.") from exc
    if value < 0:
        raise forms.ValidationError(f"{label.capitalize()} values must be zero or more.")
    return value


def selected_participants(*, members, posted_data) -> list[User]:
    """
    Members ticked as taking part in an expense (checkbox `split_include_<id>`).
    If the form sent no include checkboxes at all, everyone participates.
    """
    members = list(members)
    if not any(key.startswith("split_include_") for key in posted_data.keys()):
        return members
    return [m for m in members if posted_data.get(f"split_include_{m.id}")]


def build_splits_for_expense(*, expense: Expense, members, split_type: str, posted_data) -> list[Split]:
    """
    Build (unsaved) Split objects for an expense.

    posted_data keys:
      split_include_<user_id>  - checkbox; who takes part (optional, default all)
      split_exact_<user_id>    - for EXACT splits
      split_percent_<user_id>  - for PERCENT splits

    Raises forms.ValidationError on any invalid input.
    """
    participants = selected_participants(members=members, posted_data=posted_data)
    if not participants:
        raise forms.ValidationError("Select at least one person to split this expense with.")

    amount: Decimal = Decimal(expense.amount).quantize(CENT)

    def fix_rounding(splits: list[Split]) -> list[Split]:
        # Put any leftover cent(s) on the payer if they take part, else the first participant.
        diff = (amount - sum((s.amount for s in splits), Decimal("0.00"))).quantize(CENT)
        if diff:
            target = next((s for s in splits if s.user_id == expense.payer_id), splits[0])
            target.amount = (target.amount + diff).quantize(CENT)
        return splits

    if split_type == Expense.SplitType.EQUAL:
        per = (amount / len(participants)).quantize(CENT)
        return fix_rounding([Split(expense=expense, user=m, amount=per) for m in participants])

    if split_type == Expense.SplitType.EXACT:
        splits, total = [], Decimal("0.00")
        for m in participants:
            raw = (posted_data.get(f"split_exact_{m.id}") or "").strip()
            if not raw:
                raise forms.ValidationError(f"Enter an exact amount for {m.username}.")
            amt = _parse_decimal(raw, "amount")
            splits.append(Split(expense=expense, user=m, amount=amt))
            total += amt
        if total != amount:
            raise forms.ValidationError(
                f"Exact amounts add up to ₹{total}, but the expense is ₹{amount}."
            )
        return splits

    if split_type == Expense.SplitType.PERCENT:
        rows, total_pct = [], Decimal("0.00")
        for m in participants:
            raw = (posted_data.get(f"split_percent_{m.id}") or "").strip()
            if not raw:
                raise forms.ValidationError(f"Enter a percentage for {m.username}.")
            pct = _parse_decimal(raw, "percent")
            rows.append((m, pct))
            total_pct += pct
        if total_pct != Decimal("100.00"):
            raise forms.ValidationError(f"Percentages add up to {total_pct}%, they must total 100%.")
        splits = [
            Split(expense=expense, user=m, amount=(amount * pct / 100).quantize(CENT), percent=pct)
            for m, pct in rows
        ]
        return fix_rounding(splits)

    raise forms.ValidationError("Unknown split type.")


# ---------------------------------------------------------------- settlements


class SettlementForm(forms.ModelForm):
    class Meta:
        model = Settlement
        fields = ["payer", "receiver", "amount", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional, e.g. UPI"}),
        }
        labels = {"payer": "Who paid", "receiver": "Paid to"}

    def __init__(self, *args, group: Group, **kwargs):
        super().__init__(*args, **kwargs)
        self.group = group
        members = group.members.all().order_by("username")
        self.fields["payer"].queryset = members
        self.fields["receiver"].queryset = members
        _style(self)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount.quantize(CENT)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("payer") and cleaned.get("payer") == cleaned.get("receiver"):
            raise forms.ValidationError("Payer and receiver must be different people.")
        return cleaned

    def save(self, commit=True):
        obj: Settlement = super().save(commit=False)
        obj.group = self.group
        if commit:
            obj.save()
        return obj
