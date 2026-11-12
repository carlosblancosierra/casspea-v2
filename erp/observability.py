"""Error reporting (Sentry) and long-lived logs (CloudWatch).

Both are switched on by environment variables only, so local runs, tests and
any deploy without them configured behave exactly as before.

Sentry
    SENTRY_DSN                 overrides the built-in production DSN (Sentry project casspea-api);
                               set it to an empty string to switch Sentry off
    SENTRY_ENVIRONMENT         defaults to "production" on Heroku, else ENVIRONMENT
    SENTRY_TRACES_SAMPLE_RATE  share of requests traced for performance, 0..1 (default 0)

    Unhandled exceptions in views, management commands and django-q tasks are
    reported, and so is every logger.error / logger.exception call — which is
    how most of this codebase handles failures it catches.

CloudWatch
    CLOUDWATCH_LOG_GROUP       enables it, e.g. "casspea-api"
    CLOUDWATCH_RETENTION_DAYS  how long CloudWatch keeps them (default 30)

    Heroku only keeps the last 1,500 log lines. With this set, every log line
    the app writes also goes to CloudWatch, one stream per dyno (web.1,
    worker.1...), kept for a month. It reuses the AWS keys the app already has
    for S3, which need logs:CreateLogGroup, logs:CreateLogStream,
    logs:PutLogEvents and logs:PutRetentionPolicy.
"""
import json
import logging
import os
import sys


def _release():
    # SENTRY_RELEASE wins; otherwise Heroku's dyno metadata
    # (`heroku labs:enable runtime-dyno-metadata`) gives the deployed commit.
    for name in ('SENTRY_RELEASE', 'HEROKU_SLUG_COMMIT', 'SOURCE_VERSION', 'HEROKU_RELEASE_VERSION'):
        if os.environ.get(name):
            return os.environ[name]
    return None


def _tidy_structlog_event(event, hint):
    """Turn a structlog JSON line into a readable, groupable Sentry issue.

    In production structlog hands the stdlib logger one rendered JSON string,
    timestamp included, so without this every occurrence would be its own
    Sentry issue titled with raw JSON. Here the title becomes the event name
    ("stripe_session_failed") and the other fields go to "extra".
    """
    entry = event.get('logentry') or {}
    message = entry.get('message')
    if not (isinstance(message, str) and message.startswith('{')):
        return event
    try:
        data = json.loads(message)
    except ValueError:
        return event
    if not isinstance(data, dict) or 'event' not in data:
        return event
    title = str(data.pop('event'))
    for key in ('timestamp', 'level', 'logger'):
        data.pop(key, None)
    event['logentry'] = {'message': title, 'formatted': title, 'params': []}
    event.setdefault('extra', {}).update(data)
    return event


def init_sentry(dsn, environment):
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=_release(),
        integrations=[
            DjangoIntegration(),
            # INFO and up become breadcrumbs, ERROR and up become Sentry issues.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0') or 0),
        # Customers' names, emails and addresses stay out of Sentry.
        send_default_pii=False,
        before_send=_tidy_structlog_event,
    )
    # Bots probing with a wrong Host header: noise, not bugs.
    ignore_logger('django.security.DisallowedHost')


class SafeCloudWatchHandler(logging.Handler):
    """CloudWatch handler that can never stop the app from starting.

    watchtower talks to AWS while it is being built; a missing permission or a
    network blip there would otherwise crash every dyno at boot. If that
    happens this handler says so once on stderr and does nothing after.
    """

    def __init__(self, log_group, retention_days=30):
        super().__init__()
        self._inner = None
        try:
            import watchtower

            self._inner = watchtower.CloudWatchLogHandler(
                log_group_name=log_group,
                log_stream_name=os.environ.get('DYNO') or '{machine_name}/{program_name}',
                log_group_retention_days=retention_days,
                send_interval=10,
            )
        except Exception as exc:  # noqa: BLE001 — logging must not take the site down
            print(f'CloudWatch logging disabled: {exc!r}', file=sys.stderr)

    def setFormatter(self, fmt):
        super().setFormatter(fmt)
        if self._inner is not None:
            self._inner.setFormatter(fmt)

    def emit(self, record):
        if self._inner is not None:
            self._inner.emit(record)

    def flush(self):
        if self._inner is not None:
            self._inner.flush()

    def close(self):
        if self._inner is not None:
            self._inner.close()
        super().close()
