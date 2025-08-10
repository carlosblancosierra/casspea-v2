from django.core.management import call_command


def mail_pending_sessions(*args, **kwargs):
    """Mail pending sessions task."""
    try:
        call_command('mail_pending_sessions')
    except Exception as e:
        print(e)
        raise


def test_task(*args, **kwargs):
    """Test task."""
    print("Test task")


def send_review_requests_task(*args, **kwargs):
    from mails.services import ReviewRequestMailProcessor
    processor = ReviewRequestMailProcessor()
    return processor.send_review_requests(test=False)
