from django.conf import settings

# The refresh cookie is only ever needed by refresh/logout, so browsers send it nowhere else.
REFRESH_COOKIE_PATH = "/api/auth/user/"


def access_lifetime_seconds() -> int:
    return int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())


def set_auth_cookies(response, access_token, refresh_token):
    common = {"httponly": True, "secure": settings.COOKIE_SECURE, "samesite": settings.COOKIE_SAMESITE}
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE,
        str(access_token),
        max_age=access_lifetime_seconds(),
        path="/",
        **common,
    )
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        str(refresh_token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=REFRESH_COOKIE_PATH,
        **common,
    )


def clear_auth_cookies(response):
    response.delete_cookie(settings.JWT_ACCESS_COOKIE, path="/", samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(settings.JWT_REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite=settings.COOKIE_SAMESITE)
