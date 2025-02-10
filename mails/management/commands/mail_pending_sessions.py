from django.core.management.base import BaseCommand
from mails.services import PendingCheckoutSessionsMailProcessor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Process pending checkout sessions for non-paid orders. "
        "Use --dry-run to log session details only, --test to send emails to ADMINS via mail_admins, "
        "or run without flags for the real process."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Log session details without sending emails or creating log records.'
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Send test emails using django mail_admins (to the ADMINS defined in settings).'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        test = options.get('test', False)

        if dry_run and test:
            self.stdout.write(self.style.ERROR("Please choose either --dry-run or --test."))
            return

        processor = PendingCheckoutSessionsMailProcessor()

        if dry_run:
            count = processor.send_pending_mails_dry_run()
            self.stdout.write(f"Dry run mode: {count} pending checkout session(s) found.")
        elif test:
            count = processor.send_pending_mails_test()
            self.stdout.write(f"Test mode: Processed {count} checkout session(s) via mail_admins.")
        else:
            count = processor.send_pending_mails()
            self.stdout.write(f"Real mode: Processed and emailed {count} checkout session(s).")