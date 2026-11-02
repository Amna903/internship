from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitoring.models import PredictionLog

KEEP_DAYS = 90


class Command(BaseCommand):
    help = "Delete prediction logs older than 90 days."

    def handle(self, *args, **options):
        deleted, _ = PredictionLog.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()
        self.stdout.write(f"deleted {deleted} prediction log row(s)")
