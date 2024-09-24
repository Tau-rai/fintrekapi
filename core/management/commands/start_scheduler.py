# core/management/commands/start_scheduler.py
from django.core.management.base import BaseCommand
from core.scheduler import add_job_if_not_exists, start

class Command(BaseCommand):
    help = 'Starts the APScheduler and adds necessary jobs'

    def handle(self, *args, **kwargs):
        add_job_if_not_exists()
        start()
        self.stdout.write(self.style.SUCCESS('Scheduler started and jobs added if not exist.'))
