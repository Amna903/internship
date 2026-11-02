"""Run the 18 frozen evaluation cases against the local model for settings A (shipped) and B (comparison)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant import evaluate
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Evaluate the assistant on the frozen cases; writes assistant/eval/eval_results.json and eval_report.md."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Admin recorded as approving the U3b test upload.")

    def handle(self, *args, admin, **options):
        actor = User.objects.filter(email=admin.strip().lower(), role="admin").first()
        if actor is None:
            raise CommandError("No admin account with that email.")
        try:
            result = evaluate.evaluate(get_llm(), get_embedder(), actor, settings.ASSISTANT["SEED"])
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        evaluate.save(result)
        for name, s in evaluate.summary(result, evaluate.load_cases()).items():
            self.stdout.write(f"{name}: {s['passed']} of 18 cases passed")
