# Expense Tracker — Splitwise-style group expenses (Django · SQLite · Chart.js)

Track shared expenses in groups, split them equally / by exact amounts / by percentages,
see who owes whom, and record settlements — with analytics dashboards built on Chart.js.

## Features
- **Auth** – sign up, log in, log out (Django auth, validated forms).
- **Groups** – create, rename, add/remove members (members with unsettled balances can't be removed), leave group.
- **Expenses (full CRUD)** – description, amount, date, category, payer.
  - **Equal** split (optionally among a subset of members; leftover paise go to the payer)
  - **Exact** split (must add up to the total)
  - **Percentage** split (must total 100%)
  - Live split preview in the form; existing splits pre-filled when editing.
- **Balances** – net balance per member, computed from expenses, splits and settlements.
- **Who owes whom** – debts simplified into the fewest payments, with one-click "Settle".
- **Settlements (full CRUD)** – record, edit, delete repayments.
- **Dashboards** – personal dashboard (owed / owe / net across all groups, spending by category & month) and
  per-group dashboard (category doughnut, paid-vs-share per member, monthly bars, daily trend, category filter).
- Authorization: users only ever see groups they belong to (404 otherwise).
- Django admin for all models; demo seed command; test suite.

## Quick start
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # optional: demo users alice/bob/charlie/diya, password pass1234
python manage.py runserver
```
Open http://127.0.0.1:8000 and log in as `alice` / `pass1234`.
Admin: `python manage.py createsuperuser`, then visit `/admin/`.

Run tests: `python manage.py test tracker`

## Project structure
```
core/                     settings, root urls
tracker/
  models.py               Category, Group, Expense, Split, Settlement
  forms.py                auth/group/expense/settlement forms + split engine (build_splits_for_expense)
  views.py                all pages
  services/balances.py    net balances, debt simplification, per-user summary
  services/authz.py       membership-scoped lookups (404 for non-members)
  templatetags/           small template helpers
  templates/tracker/      Bootstrap 5 templates
  static/tracker/js/      dashboard.js (Chart.js), expense_form.js (live split preview)
  management/commands/seed_demo.py
  tests.py
```

## Balance convention
Positive = the member is owed money; negative = the member owes money.
The payer is credited the full expense, each participant is debited their split, and
a settlement credits the payer and debits the receiver. All balances in a group sum to zero.

## Config (optional env vars)
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS` (comma-separated).
