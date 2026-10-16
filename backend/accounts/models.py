from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    @staticmethod
    def _normalize(email: str) -> str:
        return email.strip().lower()

    def get_by_natural_key(self, username):
        # authenticate() goes through here, so logins are case-insensitive.
        return self.get(email=self._normalize(username))

    def _create(self, email, password, role):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self._normalize(email), role=role)
        user.set_password(password)  # hashes; password=None -> unusable password
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None):
        return self._create(email, password, User.Role.USER)

    def create_admin(self, email, password):
        return self._create(email, password, User.Role.ADMIN)

    # `createsuperuser` compatibility: a "superuser" is simply an admin here.
    def create_superuser(self, email, password=None, **extra):
        return self._create(email, password, User.Role.ADMIN)


class User(AbstractBaseUser):
    """Single account table for both roles.

    The ``role`` column is the only source of truth for authorization. Admin rows can only be
    created through ``UserManager.create_admin`` (management command / seed); the public signup
    serializer has no ``role`` field at all.
    """

    class Role(models.TextChoices):
        USER = "user", "Standard user"
        ADMIN = "admin", "Administrator"

    email = models.EmailField(max_length=254, unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        constraints = [
            # DB-level guarantee that emails are stored normalized, so the plain unique index on
            # `email` is effectively a case-insensitive uniqueness rule.
            models.CheckConstraint(condition=Q(email=Lower("email")), name="user_email_is_lowercase"),
            models.CheckConstraint(condition=Q(role__in=["user", "admin"]), name="user_role_is_valid"),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    def __str__(self) -> str:
        return self.email
