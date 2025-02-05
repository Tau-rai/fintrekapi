"""Module for views of the core app."""
from datetime import datetime
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.utils import IntegrityError
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import generics, viewsets, permissions, status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from datetime import date
import requests
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Category, MonthlyBudget, Transaction, SavingsGoal, UserProfile, Subscription, Income, Expense
from .models import Category, MonthlyBudget, Transaction, SavingsGoal, UserProfile, Subscription, Insight
from .serializers import (CategorySerializer, LoginSerializer,
                          MonthlyBudgetSerializer, RegisterSerializer,
                          TransactionSerializer, UserProfileSerializer, SavingsGoalSerializer, SubscriptionSerializer, InsightSerializer)
from django.core.management import call_command
from django.core.cache import cache
from django.http import JsonResponse
from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes


class UserProfileViewSet(viewsets.ModelViewSet):
    """User profile view."""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser]  # Allow file uploads
    http_method_names = ['get', 'put', 'patch']

    def get_queryset(self):
        """Filter user profile by the current user."""
        user_id = self.request.user.id
        cache_key = f"user_profile_{user_id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return [cached_data]
        queryset = UserProfile.objects.filter(user=self.request.user)
        if queryset.exists():
            cache.set(cache_key, queryset.first(), timeout=3600)  # Cache for 1 hour
        return queryset

    def update(self, request, *args, **kwargs):
        """Handle profile updates."""
        user_profile = self.get_object()
        serializer = self.get_serializer(user_profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # Update the User model fields if needed
        user = user_profile.user
        user.first_name = request.data.get('first_name', user.first_name)
        user.last_name = request.data.get('last_name', user.last_name)
        user.save()

        # Handle placeholder logic if the image field is empty
        if not user_profile.image and not request.data.get('profile_picture'):
            placeholder_url = 'https://picsum.photos/150'
            response = requests.get(placeholder_url)
            if response.status_code == 200:
                user_profile.image.save('placeholder.jpg', ContentFile(response.content), save=False)

        # Save and invalidate cache
        user_profile.save()
        cache.delete(f"user_profile_{user_profile.user.id}")

        return Response(serializer.data, status=status.HTTP_200_OK)

    def perform_update(self, serializer):
        """Set the user before saving the updated profile."""
        serializer.save(user=self.request.user)


class RegisterView(generics.CreateAPIView):
    """Register view."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        """User registration with password hashing and profile creation."""
        user = serializer.save()  # Save the user instance
        password = self.request.data.get('password')
        user.set_password(password)  # Set and hash the password
        user.save()

        # Create a UserProfile for the newly registered user
        UserProfile.objects.create(
            user=user,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            username=user.username
        )

    def create(self, request, *args, **kwargs):
        """Handle user registration, token generation, and profile creation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Perform the actual creation of the user and profile
        self.perform_create(serializer)

        # Generate a token for the registered user
        user = serializer.instance
        refresh = RefreshToken.for_user(user)
        token = str(refresh.access_token)

        # Return user data and token
        return Response({
            'user': RegisterSerializer(user).data,
            'token': token
        }, status=status.HTTP_201_CREATED)


class LoginView(generics.GenericAPIView):
    """Login view."""
    serializer_class = TokenObtainPairSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """Login post method."""
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise ValidationError({"detail": "Invalid credentials."})

        # Extract the token from the validated data
        token_data = serializer.validated_data
        return Response({'token': token_data['access']}, status=status.HTTP_200_OK)


class TransactionViewSet(viewsets.ModelViewSet):
    """Transaction view."""
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Transaction.objects.none()

        # Generate a cache key based on user ID and optional filters
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        category_id = self.request.query_params.get('category')
        cache_key = f"transactions_{user.id}_{start_date}_{end_date}_{category_id}"

        # Check if the result is cached
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        # Query the database if not cached
        queryset = Transaction.objects.filter(user=user)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        # Cache the result for 1 hour
        cache.set(cache_key, list(queryset), timeout=3600)
        return queryset

def perform_create(self, serializer):
    """Set the user field and invalidate related caches."""
    user = self.request.user
    serializer.save(user=user)

    # Invalidate caches for this user
    cache.delete(f"transactions_{user.id}")
    cache.delete(f"transaction_summary_{user.id}")

def perform_update(self, serializer):
    """Invalidate caches after updating a transaction."""
    user = self.request.user
    serializer.save()

    # Invalidate caches for this user
    cache.delete(f"transactions_{user.id}")
    cache.delete(f"transaction_summary_{user.id}")

def perform_destroy(self, instance):
    """Invalidate caches after deleting a transaction."""
    user = instance.user
    instance.delete()

    # Invalidate caches for this user
    cache.delete(f"transactions_{user.id}")
    cache.delete(f"transaction_summary_{user.id}")

    @action(detail=False, methods=['get'])
    def summary(self, request):
        user = request.user
        if not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        cache_key = f"transaction_summary_{user.id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data, status=status.HTTP_200_OK)

        # Calculate summary data
        incomes = Transaction.objects.filter(user=user, amount__gt=0).aggregate(total=Sum('amount'))['total'] or 0
        expenses = Transaction.objects.filter(user=user, amount__lt=0).aggregate(total=Sum('amount'))['total'] or 0

        top_categories = (
            Transaction.objects
            .filter(user=user, amount__lt=0)
            .values('category__name')
            .annotate(total_spent=Sum('amount'))
            .order_by('-total_spent')[:5]  # Top 5 categories
        )

        data = {
            "incomes": str(incomes),
            "expenses": str(-expenses),
            "top_categories": [
                {"category": item['category__name'], "total_spent": str(-item['total_spent'])}
                for item in top_categories
            ],
        }

        # Cache the result for 1 hour
        cache.set(cache_key, data, timeout=3600)
        return Response(data, status=status.HTTP_200_OK)

class CategoryViewSet(viewsets.ModelViewSet):
    """Category view."""
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get_queryset(self):
        """Filter categories by the current user."""
        user = self.request.user
        if not user.is_authenticated:
            return Category.objects.none()

        return Category.objects.filter(user=user)

    def perform_create(self, serializer):
        """Set the user field when creating a new category."""
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Ensure only the owner can delete a category."""
        instance = self.get_object()
        if instance.user != request.user:
            return Response({"detail": "Not authorized"}, status=status.HTTP_403_FORBIDDEN)

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MonthlyBudgetViewSet(viewsets.ModelViewSet):
    """Monthly budget view."""
    queryset = MonthlyBudget.objects.none()
    serializer_class = MonthlyBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return MonthlyBudget.objects.none()

        month_str = self.request.query_params.get('month', timezone.now().date().replace(day=1).strftime('%Y-%m-%d'))
        try:
            month = datetime.strptime(month_str, '%Y-%m-%d').date().replace(day=1)
            cache_key = f"monthly_budget_{user.id}_{month.strftime('%Y-%m')}"
            cached_data = cache.get(cache_key)
            if cached_data:
                return [cached_data]
            queryset = MonthlyBudget.objects.filter(user=user, month__year=month.year, month__month=month.month)
            if queryset.exists():
                cache.set(cache_key, queryset.first(), timeout=3600)  # Cache for 1 hour
            return queryset
        except ValueError:
            return MonthlyBudget.objects.none()

    def perform_create(self, serializer):
        """Check if a budget for this user and month already exists."""
        month = serializer.validated_data.get('month')
        if MonthlyBudget.objects.filter(user=self.request.user, month=month).exists():
            raise ValidationError({"error": "A budget already exists for this month."})
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get'])
    def check_budget_status(self, request):
        """Check the budget status for the current month."""
        user = request.user
        month_str = request.query_params.get('month', timezone.now().date().replace(day=1).strftime('%Y-%m-%d'))

        try:
            month = datetime.strptime(month_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'detail': 'Invalid month format.'}, status=status.HTTP_400_BAD_REQUEST)

        cache_key = f"budget_status_{user.id}_{month.strftime('%Y-%m')}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data, status=status.HTTP_200_OK)

        budget = MonthlyBudget.objects.filter(user=user, month__year=month.year, month__month=month.month).first()
        if not budget:
            return Response({'detail': 'Budget not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = {
            'budget_amount': str(budget.budget_amount),
            'expenditure': str(budget.get_expenditure()),
            'is_over_budget': budget.is_over_budget(),
            'remaining_budget': budget.get_remaining_budget(),
        }

        # Cache the result for 1 hour
        cache.set(cache_key, data, timeout=3600)
        return Response(data, status=status.HTTP_200_OK)

    # def create(self, request, *args, **kwargs):
    #     user = request.user
    #     month_str = request.data.get('month')
    #     budget_amount = request.data.get('budget_amount')

    #     # Validate that month is provided and in the correct format
    #     if not month_str:
    #         return Response({'error': 'Month is required.'}, status=status.HTTP_400_BAD_REQUEST)

    #     try:
    #         month = datetime.strptime(month_str, '%Y-%m-%d').date()
    #     except ValueError:
    #         return Response({'error': 'Invalid month format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

    #     # Validate that budget_amount is provided and is a valid decimal number
    #     if budget_amount is None:
    #         return Response({'error': 'Budget amount is required.'}, status=status.HTTP_400_BAD_REQUEST)

    #     try:
    #         budget_amount = Decimal(budget_amount)
    #         if budget_amount <= 0:
    #             raise ValueError
    #     except (ValueError, TypeError, InvalidOperation):
    #         return Response({'error': 'Budget amount must be a positive number.'}, status=status.HTTP_400_BAD_REQUEST)

    #     # Check if a budget already exists for the same user and month
    #     if MonthlyBudget.objects.filter(user=user, month=month).exists():
    #         return Response({'error': 'A budget for this month already exists.'}, status=status.HTTP_400_BAD_REQUEST)

    #     # Create a new budget for the user and month
    #     try:
    #         monthly_budget = MonthlyBudget.objects.create(
    #             user=user,
    #             month=month,
    #             budget_amount=budget_amount
    #         )
    #         return Response({'message': 'Budget created successfully', 'budget': {
    #             'id': monthly_budget.id,
    #             'user': monthly_budget.user.id,
    #             'month': monthly_budget.month,
    #             'budget_amount': monthly_budget.budget_amount,
    #         }}, status=status.HTTP_201_CREATED)

    #     except IntegrityError:
    #         return Response({'error': 'Failed to create the budget. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SavingsGoalViewSet(viewsets.ModelViewSet):
    """Savings goal view."""
    queryset = SavingsGoal.objects.all()
    serializer_class = SavingsGoalSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            cache_key = f"savings_goal_{user.id}"
            cached_data = cache.get(cache_key)
            if cached_data:
                return [cached_data]
            queryset = SavingsGoal.objects.filter(user=user)
            if queryset.exists():
                cache.set(cache_key, queryset.first(), timeout=3600)  # Cache for 1 hour
            return queryset
        return SavingsGoal.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        goal_amount = serializer.validated_data['goal_amount']
        goal_date = serializer.validated_data['goal_date']

        try:
            savings_goal = user.savingsgoal
            savings_goal.goal_amount = goal_amount
            savings_goal.goal_date = goal_date
            savings_goal.save()
        except SavingsGoal.DoesNotExist:
            savings_goal = SavingsGoal.objects.create(
                user=user,
                goal_amount=goal_amount,
                goal_date=goal_date,
            )

        cache.delete(f"savings_goal_{user.id}")
        return savings_goal

    @action(detail=False, methods=['post'])
    def add_savings(self, request):
        """Add savings amount to the savings goal."""
        user = request.user
        goal = get_object_or_404(SavingsGoal, user=user)

        if goal.is_goal_reached():
            return Response({'detail': 'Goal has already been reached.'}, status=status.HTTP_400_BAD_REQUEST)

        savings_amount = request.data.get('savings_amount', None)
        if savings_amount is None:
            return Response({'detail': 'Savings amount not provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            savings_amount = Decimal(savings_amount)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid savings amount format.'}, status=status.HTTP_400_BAD_REQUEST)

        if savings_amount <= 0:
            return Response({'detail': 'Savings amount must be greater than zero.'}, status=status.HTTP_400_BAD_REQUEST)

        goal.current_savings += savings_amount
        goal.save()

        cache.delete(f"savings_goal_{user.id}")
        if goal.is_goal_reached():
            return Response({'detail': 'Congratulations! Goal reached and exceeded!'}, status=status.HTTP_200_OK)
        else:
            return Response({'detail': 'Savings added successfully.'}, status=status.HTTP_200_OK)


class SubscriptionViewSet(viewsets.ModelViewSet):
    """Subscription view."""
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get_queryset(self):
        """Filter subscriptions by the current user and optionally by month and year."""
        user = self.request.user
        if not user.is_authenticated:
            return Subscription.objects.none()

        queryset = Subscription.objects.filter(user=user)

        # Get the month and year from query parameters
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')

        if month and year:
            try:
                # Convert month and year to integers
                month = int(month)
                year = int(year)
                # Filter the subscriptions based on month and year
                queryset = queryset.filter(due_date__month=month, due_date__year=year)
            except (ValueError, TypeError):
                # Handle invalid month or year values
                return Subscription.objects.none()

        return queryset

    def perform_create(self, serializer):
        """Set the user field and default values."""
        serializer.save(user=self.request.user, is_paid=False)

    @action(detail=True, methods=['post'])
    def mark_as_paid(self, request, pk=None):
        """Toggle the subscription's paid status."""
        subscription = self.get_object()

        # Ensure the user can only modify their own subscriptions
        if subscription.user != request.user:
            return Response({"detail": "Not authorized"}, status=status.HTTP_403_FORBIDDEN)

        # Toggle the `is_paid` status
        subscription.is_paid = not subscription.is_paid
        subscription.save(update_fields=['is_paid'])

        # Log the update timestamp
        subscription.updated_at = timezone.now()
        subscription.save(update_fields=['updated_at'])

        status_message = "paid" if subscription.is_paid else "unpaid"
        return Response({"status": f"Subscription marked as {status_message}"}, status=status.HTTP_200_OK)

class GeneratePersonalInsightView(viewsets.ViewSet):
    """
    API View to generate a personalized insight for the current user
    """
    serializer_class = InsightSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request):
        try:
            # Call management command to generate insight for this user
            call_command('generate_daily_insight', user=request.user.username)

            # Fetch the most recent user insight
            latest_insight = Insight.objects.filter(
                user=request.user,
                is_automated=False
            ).latest('date_posted')

            # Serialize and return the insight
            serializer = self.serializer_class(latest_insight)
            return Response(serializer.data)
        except Insight.DoesNotExist:
            return Response({
                'error': 'No personalized insight could be generated'
            }, status=status.HTTP_400_BAD_REQUEST)

class InsightViewSet(viewsets.ViewSet):
    """
    A ViewSet for listing insights for the authenticated user.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        page_size = min(6, Insight.objects.count())  # Set max page size to 6 or total count if less
        if page_size == 0:
            page_size = 1  # Avoid division by zero

        page = request.query_params.get('page', 1)
        try:
            page = int(page)
        except ValueError:
            page = 1

        offset = (page - 1) * page_size
        limit = offset + page_size

        cache_key = f"insights_{request.user.id}_page_{page}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)

        insights = Insight.objects.order_by('-date_posted')[offset:limit]
        total_insights = Insight.objects.count()

        serializer = InsightSerializer(insights, many=True)
        response_data = {
            'results': serializer.data,
            'page': page,
            'total_pages': (total_insights + page_size - 1) // page_size,
            'total_items': total_insights,
        }

        # Cache the response for 1 hour
        cache.set(cache_key, response_data, timeout=3600)
        return Response(response_data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_exchange_rate(request):
    from_currency = request.GET.get('from_currency', 'USD')  # Default to USD
    api_key = settings.CURRENCY_API_KEY
    api_host = settings.CURRENCY_API_HOST

    url = f"https://{api_host}/api/v1/convert-rates/fiat/from?detailed=false&currency={from_currency}"

    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': api_host,
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        data = response.json()
        return Response(data)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching exchange rate: {e}")  # Log the error
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)