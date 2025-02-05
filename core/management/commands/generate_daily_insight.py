from django.core.management.base import BaseCommand
from django.db.models import Sum, F
from django.utils import timezone
from core.models import User, Transaction, Category, Insight
import google.generativeai as genai
import os
from datetime import timedelta
import logging
import re
import http.client
import json
import requests

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate automated and user-requested financial insights'

    ALPHAV_STOCK_MARKETS_API = 'DRE4B2FF5GLA3J54'
    POLYGON_STOCK_MARKETS_API = 'YTtIr_U8aN2KK3NPvTkGzPYowrlF_0A7'

    def fetch_external_data(self):
        """
        Fetch external financial data from APIs, including inflation rates and stock market indices.
        Returns:
            dict: A dictionary containing external financial data.
        """
        try:
            inflation_rate = self.fetch_inflation_rate_africa()
            stock_index = self.fetch_stock_market_index()

            return {
                "inflation_rate": inflation_rate,
                "stock_index": stock_index,
            }
        except Exception as e:
            logger.warning(f"Error fetching external data: {e}")
            return {}

    def fetch_inflation_rate_africa(self):
        """
        Fetch the inflation rate for Africa using the RapidAPI endpoint.
        Returns:
            float: The inflation rate for Africa.
        """
        try:
            conn = http.client.HTTPSConnection("inflation-rate-around-the-world.p.rapidapi.com")
            headers = {
                'x-rapidapi-key': "4466479be2msha727fad94360df3p19db10jsn95d9b383e138",
                'x-rapidapi-host': "inflation-rate-around-the-world.p.rapidapi.com"
            }
            conn.request("GET", "/africa", headers=headers)
            res = conn.getresponse()
            data = res.read().decode("utf-8")
            inflation_data = json.loads(data)
            if "rate" in inflation_data:
                return inflation_data["rate"]
            else:
                logger.warning("Inflation rate not found in API response.")
                return 0
        except Exception as e:
            logger.warning(f"Error fetching Africa inflation rate: {e}")
            return 0

    def fetch_stock_market_index(self):
        """
        Fetch a stock market index using Alpha Vantage or Polygon API.
        Returns:
            float: The stock market index value.
        """
        try:
            symbol = "IBM"
            url = f'https://www.alphavantage.co/query?function=TIME_SERIES_WEEKLY&symbol={symbol}&apikey={self.ALPHAV_STOCK_MARKETS_API}'
            response = requests.get(url)

            if response.status_code == 200:
                data = response.json()
                if "Weekly Time Series" in data:
                    latest_date = max(data["Weekly Time Series"].keys())
                    latest_close = float(data["Weekly Time Series"][latest_date]["4. close"])
                    return latest_close
                else:
                    logger.warning("Unexpected response format from Alpha Vantage API.")
                    return self.fallback_to_polygon_api()
            else:
                logger.warning(f"Failed to fetch stock market index from Alpha Vantage: {response.status_code}")
                return self.fallback_to_polygon_api()
        except Exception as e:
            logger.warning(f"Error fetching stock market index from Alpha Vantage: {e}")
            return self.fallback_to_polygon_api()

    def fallback_to_polygon_api(self):
        """
        Fallback to Polygon API if Alpha Vantage fails.
        Returns:
            float: The stock market index value from Polygon API.
        """
        try:
            symbol = "SPY"
            url = f'https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={self.POLYGON_STOCK_MARKETS_API}'
            response = requests.get(url)

            if response.status_code == 200:
                data = response.json()
                if "results" in data and len(data["results"]) > 0:
                    latest_close = data["results"][0].get("c", 0)
                    return latest_close
                else:
                    logger.warning("Unexpected response format from Polygon API.")
                    return 0
            else:
                logger.warning(f"Failed to fetch stock market index from Polygon: {response.status_code}")
                return 0
        except Exception as e:
            logger.warning(f"Error fetching stock market index from Polygon: {e}")
            return 0

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

        # Fetch external data
        external_data = self.fetch_external_data()

        # Check if a specific user was provided
        specific_username = kwargs.get('user')
        if specific_username:
            try:
                user = User.objects.get(username=specific_username)
                self.generate_user_insight(user, model, external_data)  # Pass external_data here
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
                    insight_title, insight_content = self.generate_personalized_insight(model, metrics, external_data)
                    # Truncate title if too long
                    insight_title = self.truncate_title(insight_title)
                    # Save insight if generated successfully
                    if insight_title and insight_content:
                        Insight.objects.create(
                            title=insight_title,
                            content=insight_content,
                            user=user,
                            is_automated=True
                        )
                        self.stdout.write(self.style.SUCCESS(f'Generated automated insight for {user.username}'))
                except Exception as e:
                    logger.error(f"Error processing insights for user {user.username}: {e}")
                    self.stderr.write(self.style.ERROR(f"Error processing insights for user {user.username}: {e}"))
                    
    def generate_user_insight(self, user, model, external_data):
        """
        Generate a user-requested personalized financial insight.
        """
        try:
            # Calculate financial metrics
            metrics = self.calculate_user_financial_metrics(user)
            # Generate personalized insight
            insight_title, insight_content = self.generate_personalized_insight(model, metrics, external_data)
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
        """Calculate comprehensive financial metrics for a user."""
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        # Get category IDs for different transaction types
        income_categories = Category.objects.filter(user=user, name__icontains='income').values_list('id', flat=True)
        expense_categories = Category.objects.filter(user=user, name__icontains='expense').values_list('id', flat=True)
        savings_categories = Category.objects.filter(user=user, name__icontains='savings').values_list('id', flat=True)
        investment_categories = Category.objects.filter(user=user, name__icontains='investment').values_list('id', flat=True)

        # Calculate income, expenses, savings, and investments
        total_income = Transaction.objects.filter(
            user=user, category__id__in=income_categories, date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_expenses = Transaction.objects.filter(
            user=user, category__id__in=expense_categories, date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_savings = Transaction.objects.filter(
            user=user, category__id__in=savings_categories, date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_investments = Transaction.objects.filter(
            user=user, category__id__in=investment_categories, date__gte=thirty_days_ago
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Additional metrics
        net_income = total_income - total_expenses
        savings_rate = (total_savings / total_income * 100) if total_income > 0 else 0
        debt_to_income_ratio = ((total_expenses - total_savings) / total_income * 100) if total_income > 0 else 0

        return {
            'username': user.username,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'total_savings': total_savings,
            'total_investments': total_investments,
            'savings_rate': savings_rate,
            'net_income': net_income,
            'debt_to_income_ratio': debt_to_income_ratio,
        }

    def generate_personalized_insight(self, model, metrics, external_data):
        """Generate a personalized financial insight using Google Generative AI."""
        try:
            # Construct a detailed prompt with user's financial metrics and external data
            prompt = f"""
            Generate a personalized financial insight for {metrics['username']} based on the following data:

            User Financial Metrics:
            - Monthly Income: ${metrics['total_income']:.2f}
            - Monthly Expenses: ${metrics['total_expenses']:.2f}
            - Net Monthly Income: ${metrics['net_income']:.2f}
            - Monthly Savings: ${metrics['total_savings']:.2f}
            - Monthly Investments: ${metrics['total_investments']:.2f}
            - Savings Rate: {metrics['savings_rate']:.2f}%
            - Debt-to-Income Ratio: {metrics['debt_to_income_ratio']:.2f}%

            External Economic Context:
            - Inflation Rate: {external_data.get('inflation_rate', 'N/A')}%
            - Stock Market Index: {external_data.get('stock_index', 'N/A')}

            Provide a concise, actionable financial insight that:
            1. Highlights the user's current financial health in relation to external factors.
            2. Offers specific, personalized advice tailored to their financial situation.
            3. Suggests potential improvements considering current economic conditions.
            4. Uses a supportive and motivational tone.
            5. Ensure the title is clear and succinct (under 200 characters).

            Include both generic and personalized advice where applicable.
            """

            # Generate insight
            response = model.generate_content(prompt)
            generated_text = response.candidates[0].content.parts[0].text

            # Extract title and content from the response
            lines = generated_text.split('\n')
            title = lines[0]
            content = '\n'.join(lines[1:])

            return title, content
        except Exception as e:
            logger.error(f"Error generating personalized insight: {e}")
            return self.generate_fallback_insight(metrics, external_data)

    def generate_fallback_insight(self, metrics, external_data):
        """Generate a general financial insight with external context."""
        fallback_title = "Essential Financial Wellness Tips"
        fallback_content = f"""
        Key Financial Management Principles:
        1. Budgeting Fundamentals
        - Track income and expenses regularly.
        - Follow the 50/30/20 rule (needs/wants/savings).
        - Review and adjust budget monthly.

        2. Smart Saving Strategies
        - Build an emergency fund (3-6 months of expenses).
        - Automate savings transfers.
        - Look for high-yield savings accounts.

        3. Debt Management
        - Prioritize high-interest debt repayment.
        - Consider debt consolidation options.
        - Maintain a good credit score.

        4. Investment Basics
        - Diversify your investment portfolio.
        - Start retirement planning early.
        - Consider low-cost index funds.

        External Economic Context:
        - Current Inflation Rate: {external_data.get('inflation_rate', 'N/A')}%
        - Stock Market Index: {external_data.get('stock_index', 'N/A')}

        Remember: Financial stability comes from consistent habits and informed decisions. Adjust your strategies based on current economic conditions.
        """
        return fallback_title, fallback_content
    