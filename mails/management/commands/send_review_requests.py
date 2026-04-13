from django.core.management.base import BaseCommand
from mails.services import ReviewRequestMailProcessor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Send Trustpilot review request emails to eligible orders (paid, >7 days ago, from 2026). "
        "Use --dry-run to preview without sending, --test to send to admins only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Print eligible orders without sending emails or logging.'
        )
        parser.add_argument(
            '--test',
            action='store_true',
            dest='test',
            help='Send emails to ADMINS via mail_admins (does not log as real sends).'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        test = options.get('test', False)

        if dry_run and test:
            self.stdout.write(self.style.ERROR("Please choose either --dry-run or --test."))
            return

        processor = ReviewRequestMailProcessor()

        if dry_run:
            count = processor.send_review_requests_dry_run()
            self.stdout.write(f"Dry run: {count} eligible order(s) found.")
        elif test:
            count = processor.send_review_requests(test=True)
            self.stdout.write(f"Test mode: sent {count} review request(s) to admins.")
        else:
            count = processor.send_review_requests(test=False)
            self.stdout.write(f"Sent {count} Trustpilot review request(s).")
