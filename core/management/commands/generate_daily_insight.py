from django.core.management.base import BaseCommand
from django.db.models import Sum, F
from django.utils import timezone
from core.models import User, Transaction, Category, Insight
import google.generativeai as genai
import os
from datetime import timedelta
import logging
import re

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate automated and user-requested financial insights'

    def add_arguments(self, parser):
        """
        Add optional arguments to support manual insight generation
        """
        parser.add_argument(
            '--user', 
            type=str, 
            help='Generate insight for a specific username'
        )

    def handle(self, *args, **kwargs):
        # Configure the Google Generative AI client
        genai.configure(api_key=os.environ["G_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')

        # Check if a specific user was provided
        specific_username = kwargs.get('user')

        if specific_username:
            # Generate insight for a specific user
            try:
                user = User.objects.get(username=specific_username)
                self.generate_user_insight(user, model)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"User {specific_username} not found"))
        else:
            # Default behavior: generate insights for all active users
            users = User.objects.filter(is_active=True)
            for user in users:
                try:
                    # Calculate financial metrics
                    metrics = self.calculate_user_financial_metrics(user)
                    
                    # Generate automated daily insight
                    insight_title, insight_content = self.generate_personalized_insight(model, metrics)
                    
                    # Truncate title if too long
                    insight_title = self.truncate_title(insight_title)
                    
                    # Save insight if generated successfully
                    if insight_title and insight_content:
                        Insight.objects.create(
                            title=insight_title,
                            content=insight_content,
                            user=user,  # Link insight to user
                            is_automated=True  # Flag for automated insights
                        )
                        self.stdout.write(self.style.SUCCESS(f'Generated automated insight for {user.username}'))
                except Exception as e:
                    logger.error(f"Error processing insights for user {user.username}: {e}")
                    self.stderr.write(self.style.ERROR(f"Error processing insights for user {user.username}: {e}"))

    def generate_user_insight(self, user, model):
        """
        Generate a user-requested personalized financial insight
        """
        try:
            # Calculate financial metrics
            metrics = self.calculate_user_financial_metrics(user)
            
            # Generate personalized insight
            insight_title, insight_content = self.generate_personalized_insight(model, metrics)
            
            # Truncate title if too long
            insight_title = self.truncate_title(insight_title)
            
            # Save user-requested insight
            if insight_title and insight_content:
                Insight.objects.create(
                    title=insight_title,
                    content=insight_content,
                    user=user,
                    is_automated=False  # Flag for user-requested insights
                )
                self.stdout.write(self.style.SUCCESS(f'Generated user-requested insight for {user.username}'))
        except Exception as e:
            logger.error(f"Error generating user-requested insight for {user.username}: {e}")
            self.stderr.write(self.style.ERROR(f"Error generating user-requested insight: {e}"))

    def truncate_title(self, title):
        """
        Truncate the title to fit within 200 characters while preserving readability.
        """
        # Remove any non-alphanumeric characters and extra whitespace
        clean_title = re.sub(r'\s+', ' ', title.strip())
        
        # Truncate to 200 characters
        if len(clean_title) > 200:
            # Cut to 197 characters and add ellipsis
            truncated_title = clean_title[:197] + '...'
            return truncated_title
        
        return clean_title

    def calculate_user_financial_metrics(self, user):
        """
        Calculate comprehensive financial metrics for a user.
        """
        # Time range for calculations (last 30 days)
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        # Get category IDs for different transaction types
        try:
            income_categories = Category.objects.filter(
                user=user, 
                name__icontains='income'
            ).values_list('id', flat=True)

            expense_categories = Category.objects.filter(
                user=user, 
                name__icontains='expense'
            ).values_list('id', flat=True)

            savings_categories = Category.objects.filter(
                user=user, 
                name__icontains='savings'
            ).values_list('id', flat=True)

            investment_categories = Category.objects.filter(
                user=user, 
                name__icontains='investment'
            ).values_list('id', flat=True)
        except Exception as e:
            logger.warning(f"No specific categories found for user {user.username}: {e}")
            # Fallback to empty lists if no categories found
            income_categories = []
            expense_categories = []
            savings_categories = []
            investment_categories = []

        # Calculate income
        total_income = Transaction.objects.filter(
            user=user, 
            category__id__in=income_categories,
            date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Calculate expenses
        total_expenses = Transaction.objects.filter(
            user=user, 
            category__id__in=expense_categories,
            date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Calculate savings
        total_savings = Transaction.objects.filter(
            user=user, 
            category__id__in=savings_categories,
            date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Calculate investments
        total_investments = Transaction.objects.filter(
            user=user, 
            category__id__in=investment_categories,
            date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Calculate savings rate
        savings_rate = (total_savings / total_income * 100) if total_income > 0 else 0

        return {
            'username': user.username,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'total_savings': total_savings,
            'total_investments': total_investments,
            'savings_rate': savings_rate,
            'net_income': total_income - total_expenses
        }

    def generate_personalized_insight(self, model, metrics):
        """
        Generate a personalized financial insight using Google Generative AI.
        """
        try:
            # Construct a detailed prompt with user's financial metrics
            prompt = f"""
            Generate a personalized financial insight based on the following metrics:
            - Monthly Income: ${metrics['total_income']:.2f}
            - Monthly Expenses: ${metrics['total_expenses']:.2f}
            - Net Monthly Income: ${metrics['net_income']:.2f}
            - Monthly Savings: ${metrics['total_savings']:.2f}
            - Monthly Investments: ${metrics['total_investments']:.2f}
            - Savings Rate: {metrics['savings_rate']:.2f}%

            Provide a concise, actionable financial insight that:
            1. Highlights the user's current financial health
            2. Offers specific, personalized advice
            3. Suggests potential improvements
            4. Uses a supportive and motivational tone
            5. Ensure the title is clear and succinct (under 200 characters)
            """

            # Generate insight
            response = model.generate_content(prompt)
            
            # Extract the generated content
            generated_text = response.candidates[0].content.parts[0].text
            
            # Extract title and content from the response
            lines = generated_text.split('\n')
            title = lines[0]
            content = '\n'.join(lines[1:])
            
            return title, content

        except Exception as e:
            logger.error(f"Error generating personalized insight: {e}")
            
            # Fallback to a general insight if personalized generation fails
            return self.generate_fallback_insight(metrics)

    def generate_fallback_insight(self, metrics):
        """
        Generate a general financial insight when personalized generation fails.
        """
        fallback_title = "Essential Financial Wellness Tips"
        
        fallback_content = """
        Key Financial Management Principles:
        1. Budgeting Fundamentals
           - Track income and expenses regularly
           - Follow the 50/30/20 rule (needs/wants/savings)
           - Review and adjust budget monthly

        2. Smart Saving Strategies
           - Build emergency fund (3-6 months expenses)
           - Automate savings transfers
           - Look for high-yield savings accounts

        3. Debt Management
           - Prioritize high-interest debt repayment
           - Consider debt consolidation options
           - Maintain good credit score

        4. Investment Basics
           - Diversify investment portfolio
           - Start retirement planning early
           - Consider low-cost index funds

        Remember: Financial stability comes from consistent habits and informed decisions.
        """
        return fallback_title, fallback_content