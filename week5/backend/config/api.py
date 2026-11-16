from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.views import APIView


@method_decorator(csrf_protect, name="dispatch")
class CsrfProtectedAPIView(APIView):
    """Base class for endpoints that have no authentication class but still change state.

    DRF wraps every view in ``csrf_exempt`` and only re-enables CSRF inside
    ``SessionAuthentication``. Login/signup/logout must be CSRF-protected too (login CSRF),
    so we re-apply Django's ``csrf_protect`` to ``dispatch``.
    """

    def get_authenticate_header(self, request):
        # Without this DRF turns "not authenticated" into 403 for views with no authenticators.
        return 'Cookie realm="api"'
