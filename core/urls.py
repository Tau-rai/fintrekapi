"""Module for defining the urls of the core app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.views import LogoutView
from .views import (
    TransactionViewSet, CategoryViewSet, RegisterView, LoginView, UserProfileViewSet, MonthlyBudgetViewSet, SavingsGoalViewSet, SubscriptionViewSet, GeneratePersonalInsightView, InsightViewSet, get_exchange_rate
)

router = DefaultRouter()
router.register(r'transactions', TransactionViewSet, basename='transactions')
router.register(r'categories', CategoryViewSet, basename='categories')
router.register(r'monthly-budget', MonthlyBudgetViewSet, basename='monthlybudget')
router.register(r'profile', UserProfileViewSet, basename='userprofile')
router.register(r'savings-goal', SavingsGoalViewSet, basename='savingsgoal')
router.register(r'subscriptions', SubscriptionViewSet, basename='subscriptions')
router.register(r'insights', InsightViewSet, basename='insights')
router.register(r'generate-insight', GeneratePersonalInsightView, basename='generate-insight')

   

urlpatterns = [
    path('', include(router.urls)),
     path('api/convert-currency/', get_exchange_rate, name='convert-currency'),
    path('signup/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
   path('logout/', LogoutView.as_view(), name='logout'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
