from django.db import transaction

from profiles.models import HealthProfile

from .models import User


@transaction.atomic
def register_user(*, name: str, email: str, password: str) -> User:
    """Create a standard user and their (initially minimal) health profile together."""
    user = User.objects.create_user(email=email, password=password)
    HealthProfile.objects.create(user=user, full_name=name)
    return user
