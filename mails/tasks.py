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
