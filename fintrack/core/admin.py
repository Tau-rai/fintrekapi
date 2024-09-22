from django.contrib import admin

# Register your models here.
from .models import Transaction, Category, MonthlyBudget, UserProfile, SavingsGoal, Subscription, Insight

admin.site.register(Transaction)
admin.site.register(Category)
admin.site.register(MonthlyBudget)
admin.site.register(UserProfile)
admin.site.register(SavingsGoal)
admin.site.register(Subscription)
admin.site.register(Insight)
