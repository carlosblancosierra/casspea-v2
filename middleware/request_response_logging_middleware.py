import logging
import json

logger = logging.getLogger(__name__)

class RequestResponseLoggingMiddleware:
    """
    Middleware that logs details of every HTTP request and its corresponding response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log request details
        try:
            # Prepare basic request information
            request_info = {
                'method': request.method,
                'path': request.get_full_path(),
                'GET': dict(request.GET),
                'session': request.session.session_key,
                'user': str(request.user) if hasattr(request, 'user') else 'Anonymous',
            }
            # For methods that can contain body data
            if request.method in ['POST', 'PUT', 'PATCH']:
                if 'application/json' in request.content_type:
                    try:
                        request_info['body'] = json.loads(request.body.decode('utf-8'))
                    except Exception as e:
                        request_info['body'] = f"Error decoding JSON: {e}"
                else:
                    request_info['POST'] = dict(request.POST)
            logger.info("Incoming Request: %s", json.dumps(request_info))
        except Exception as e:
            logger.error("Error logging request: %s", e)

        # Process the request by calling the next middleware or view
        response = self.get_response(request)

        # Log response details
        try:
            content = ""
            if hasattr(response, 'content'):
                try:
                    content = response.content.decode('utf-8')
                    # Optionally, truncate the response content if it's too long
                    if len(content) > 1000:
                        content = content[:1000] + ' ... [truncated]'
                except Exception as e:
                    content = f"Error decoding response content: {e}"
            response_info = {
                'status_code': response.status_code,
                'content': content,
            }
            logger.info("Outgoing Response: %s", json.dumps(response_info))
        except Exception as e:
            logger.error("Error logging response: %s", e)

        return response 