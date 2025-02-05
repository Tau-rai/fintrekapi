"""Module for serializing the models of the core app."""
from rest_framework import serializers
from .models import ( Transaction, Category, User, MonthlyBudget, SavingsGoal, Subscription, UserProfile, Insight )
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import datetime
from decimal import Decimal
import markdown2
from rest_framework.fields import ImageField
from django.utils import timezone
from django.core.cache import cache
from django.core.validators import validate_email


class RegisterSerializer(serializers.ModelSerializer):
    """User registration serializer."""
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, data):
        """Check that the passwords match, email is unique, and validate email format."""
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password": "Passwords must match."})

        # Validate email format
        try:
            validate_email(data['email'])
        except Exception:
            raise serializers.ValidationError({"email": "Invalid email format."})

        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})

        # Password strength validation (optional)
        if len(data['password']) < 8:
            raise serializers.ValidationError({"password": "Password must be at least 8 characters long."})

        return data

    def create(self, validated_data):
        """Create the user."""
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user

class LoginSerializer(serializers.Serializer):
    """User login serializer."""
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        """Authenticate user and return token."""
        user = authenticate(username=data['username'], password=data['password'])
        if user is None:
            raise serializers.ValidationError("Invalid credentials")
        
        # Generate JWT token for the authenticated user
        refresh = RefreshToken.for_user(user)
        token = str(refresh.access_token)
        
        return {'user': user, 'token': token}


class CategorySerializer(serializers.ModelSerializer):
    """Category serializer."""
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Category
        fields = '__all__'

    def validate_name(self, value):
        """Ensure the category name is not empty."""
        if not value.strip():
            raise serializers.ValidationError("Category name cannot be empty.")
        return value


class UserProfileSerializer(serializers.ModelSerializer):
    """User profile serializer."""
    image = ImageField(required=False, allow_null=True)  # Make image optional

    class Meta:
        model = UserProfile
        fields = ['id', 'first_name', 'last_name', 'email', 'username', 'image']
        read_only_fields = ['email', 'username']

    def create(self, validated_data):
        """Create the user profile with a placeholder image if none is provided."""
        user = self.context['request'].user
        profile = UserProfile.objects.create(
            user=user,
            email=user.email,
            username=user.username,
            **validated_data
        )
        if not profile.image:
            profile.image = 'https://picsum.photos/150'
            profile.save()
        return profile

    def update(self, instance, validated_data):
        """Update the user profile."""
        user = self.context['request'].user
        instance.email = user.email
        instance.username = user.username
        return super().update(instance, validated_data)



class TransactionSerializer(serializers.ModelSerializer):
    """Transaction serializer."""
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    user = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Transaction
        fields = ['id', 'category', 'amount', 'date', 'description', 'user']
        read_only_fields = ['user', 'date']

    def validate_category(self, value):
        """Ensure the category belongs to the current user."""
        if value.user != self.context['request'].user:
            raise serializers.ValidationError("You do not have permission to use this category.")
        return value

class MonthlyBudgetSerializer(serializers.ModelSerializer):
    """Monthly budget serializer."""
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    get_expenditure = serializers.SerializerMethodField()
    is_over_budget = serializers.SerializerMethodField()
    get_remaining_budget = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyBudget
        fields = [
            'id', 'user', 'month', 'budget_amount',
            'get_expenditure', 'is_over_budget', 'get_remaining_budget'
        ]
        read_only_fields = [
            'user', 'get_expenditure', 'is_over_budget', 'get_remaining_budget'
        ]

    def get_get_expenditure(self, obj):
        """Cache expenditure calculation."""
        cache_key = f"expenditure_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = obj.get_expenditure()
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

    def get_is_over_budget(self, obj):
        """Cache over-budget status."""
        cache_key = f"over_budget_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = obj.is_over_budget()
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

    def get_get_remaining_budget(self, obj):
        """Cache remaining budget calculation."""
        cache_key = f"remaining_budget_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = obj.get_remaining_budget()
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

class SavingsGoalSerializer(serializers.ModelSerializer):
    """Savings goal serializer."""
    is_goal_reached = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = SavingsGoal
        fields = [
            'id', 'user', 'goal_amount', 'current_savings', 'goal_date',
            'is_goal_reached', 'remaining_amount'
        ]
        read_only_fields = ['user', 'current_savings', 'is_goal_reached', 'remaining_amount']

    def validate_goal_amount(self, value):
        """Ensure the goal amount is positive."""
        if value <= 0:
            raise serializers.ValidationError("Goal amount must be greater than zero.")
        return value

    def validate_goal_date(self, value):
        """Ensure the goal date is in the future."""
        if value < timezone.now().date():
            raise serializers.ValidationError("Goal date must be in the future.")
        return value

    def get_is_goal_reached(self, obj):
        """Cache goal reached status."""
        cache_key = f"is_goal_reached_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = obj.is_goal_reached()
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

    def get_remaining_amount(self, obj):
        """Cache remaining amount calculation."""
        cache_key = f"remaining_amount_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = obj.get_remaining_amount()
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

class SubscriptionSerializer(serializers.ModelSerializer):
    """Subscription serializer."""

    class Meta:
        model = Subscription
        fields = ['id', 'name', 'amount', 'frequency', 'payment_method', 'due_date', 'is_paid']
        read_only_fields = ['id', 'user']

    def validate_amount(self, value):
        """Ensure the subscription amount is positive."""
        if value <= 0:
            raise serializers.ValidationError("Subscription amount must be greater than zero.")
        return value

    def validate_due_date(self, value):
        """Ensure the due date is in the future."""
        if value < timezone.now().date():
            raise serializers.ValidationError("Due date must be in the future.")
        return value



class InsightSerializer(serializers.ModelSerializer):
    """Insights serializer with Markdown to HTML conversion."""
    formatted_content = serializers.SerializerMethodField()
    is_automated = serializers.BooleanField(read_only=True)

    class Meta:
        model = Insight
        fields = ['id', 'title', 'content', 'formatted_content', 'date_posted', 'is_automated']

    def get_formatted_content(self, obj):
        """Cache formatted content."""
        cache_key = f"insight_formatted_content_{obj.id}"
        cached_value = cache.get(cache_key)
        if cached_value is None:
            cached_value = markdown2.markdown(obj.content) if obj.content else ''
            cache.set(cache_key, cached_value, timeout=3600)  # Cache for 1 hour
        return cached_value

       