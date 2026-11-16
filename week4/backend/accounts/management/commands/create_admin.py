import getpass
import os
import sys

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from accounts.models import User


class Command(BaseCommand):
    help = (
        "Create an admin account. This is the ONLY way admins come into existence "
        "(there is no public admin signup endpoint)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--password-env",
            default="ADMIN_PASSWORD",
            help="Name of the environment variable holding the password (default: ADMIN_PASSWORD). "
            "If unset, you are prompted. Passwords are never accepted as CLI arguments "
            "so they do not end up in shell history.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError(f"'{email}' is not a valid email address.")
        if User.objects.filter(email=email).exists():
            raise CommandError(f"An account with email '{email}' already exists.")

        password = os.environ.get(options["password_env"])
        if not password:
            if not sys.stdin.isatty():
                raise CommandError(f"Set ${options['password_env']} or run interactively to be prompted.")
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords do not match.")

        try:
            validate_password(password, user=User(email=email))
        except ValidationError as exc:
            raise CommandError("Weak password: " + " ".join(exc.messages))

        user = User.objects.create_admin(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Admin created: {user.email}"))
