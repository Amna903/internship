"""Set the assistant's floor, top-k and groundedness threshold on the development questions (needs the local model)."""

from django.core.management.base import BaseCommand

from assistant import tuning
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Tune the assistant on the development questions only; writes assistant/dev/dev_tuning.{json,md}."

    def handle(self, *args, **options):
        result = tuning.tune(get_llm(), get_embedder())
        tuning.save(result)
        c = result["chosen"]
        self.stdout.write(f"floor {c['floor']:.2f}, top-k {c['top_k']}, groundedness threshold "
                          f"{c['effective_groundedness_threshold']:.2f}; correct by top-k {c['correct_by_top_k']}; "
                          f"incorrect answers blocked by the threshold: {c['incorrect_blocked']}")
