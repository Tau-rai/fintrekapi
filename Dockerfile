# Dockerfile

FROM python:3.10

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Add the wait-for-it script
COPY wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

# Expose the application port
EXPOSE 8000

# Command to wait for the db and then run migrations and start the application
CMD ["/wait-for-it.sh", "db:5432", "--", "sh", "-c", "python manage.py migrate && gunicorn finpulse.wsgi:application --bind 0.0.0.0:8000"]
