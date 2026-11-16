"""Generation evaluation on the frozen Week 5 set (Step 4): oracle context (A) and end to end (B). Needs the model."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant import generation_eval
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Evaluate generation separately from retrieval; writes assistant/eval/generation_eval.{json,md}."

    def handle(self, *args, **options):
        cases = generation_eval.load_cases()
        try:
            r = generation_eval.evaluate(get_llm(), get_embedder(), settings.ASSISTANT["SEED"], cases)
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        path = generation_eval.save(r, cases)
        for m, label in (("A", "oracle context"), ("B", "end to end")):
            o = r["modes"][m]["overall"]
            self.stdout.write(f"{m} ({label}): key fact {o['key_fact_ok']}/{o['answerable']}, false abstention "
                              f"{o['false_abstention']}, wrong {o['answered_wrong']}, abstained {o['abstained']}/{o['unanswerable']}")
        self.stdout.write(f"Wrote {path.name}.")
