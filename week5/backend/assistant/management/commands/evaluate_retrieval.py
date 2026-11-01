"""Retrieval-only evaluation on the frozen Week 5 set (no language model is called)."""

from django.core.management.base import BaseCommand, CommandError

from assistant import retrieval_eval
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import LLMError


class Command(BaseCommand):
    help = "Evaluate retrieval on the frozen Week 5 questions; writes assistant/eval/retrieval_<label>.{json,md}."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="baseline", help="Name of this run, e.g. baseline or after.")

    def handle(self, *args, label, **options):
        if not label.replace("_", "").isalnum():
            raise CommandError("The label may contain only letters, digits and underscores.")
        cases = retrieval_eval.load_cases()
        try:
            result = retrieval_eval.evaluate(get_embedder(), cases, label=label)
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        except LLMError as exc:
            raise CommandError(f"Embedding failed ({exc.reason}); nothing was written.") from None
        j, m = retrieval_eval.save(result, cases)
        o = result["overall"]
        self.stdout.write(f"{label}: Recall@1 {o['recall@1']:.0%}, Recall@3 {o['recall@3']:.0%}, MRR {o['mrr']:.2f}, "
                          f"as shipped {o['shipped_hit_rate']:.0%}, false retrieval {o['false_retrieval_rate']:.0%}. "
                          f"Wrote {m.name}.")
