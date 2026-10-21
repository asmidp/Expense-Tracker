from django.contrib import admin

from tracker.models import Category, Expense, Group, Settlement, Split


class SplitInline(admin.TabularInline):
    model = Split
    extra = 0


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    filter_horizontal = ("members",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "group", "payer", "amount", "split_type", "category", "date")
    list_filter = ("split_type", "category", "group")
    search_fields = ("description",)
    inlines = [SplitInline]


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("group", "payer", "receiver", "amount", "date")
    list_filter = ("group",)


admin.site.register(Category)
