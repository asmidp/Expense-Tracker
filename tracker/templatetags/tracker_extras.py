from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def absval(value):
    """Absolute value, e.g. to show '₹50.00' for a balance of -50.00."""
    try:
        return abs(Decimal(value))
    except Exception:
        return value
