"""Choose the relevance check on the dev cases, or (--frozen) score the shipped check once on the frozen set."""

from django.core.management.base import BaseCommand

from assistant import relevance_eval


class Command(BaseCommand):
    help = "Relevance check: choose on dev cases, or score on the frozen relevance set with --frozen."

    def add_arguments(self, parser):
        parser.add_argument("--frozen", action="store_true", help="score the shipped check on the frozen set")

    def handle(self, *args, frozen=False, **options):
        if frozen:
            r = relevance_eval.write_frozen()["shipped"]
            self.stdout.write(f"frozen: stopped {r['stopped_bad']}/{r['bad']}, kept {r['kept_good']}/{r['good']}")
        else:
            c = relevance_eval.write_dev()["chosen"]
            self.stdout.write(f"chosen on dev: {c}")
