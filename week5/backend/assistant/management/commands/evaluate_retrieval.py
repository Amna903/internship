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
        parser.add_argument("--selection-winner", action="store_true",
                            help="Use the dev winner from assistant/dev/retrieval_selection.json (Step 3 'after').")
        parser.add_argument("--chunk-tokens", type=int, help="Override the chunk size (the reporting-only chunk-size table).")
        parser.add_argument("--filters", action="store_true", help="Apply each case's labelled area as the opt-in filter.")

    def handle(self, *args, label, selection_winner=False, chunk_tokens=None, filters=False, **options):
        if not label.replace("_", "").isalnum():
            raise CommandError("The label may contain only letters, digits and underscores.")
        cases = retrieval_eval.load_cases()
        cfg = None
        if selection_winner or chunk_tokens:
            import json
            from dataclasses import replace
            from assistant import retrieval_select
            from assistant.indexing import RetrievalConfig
            if selection_winner:
                winner = json.loads((retrieval_select.OUT / "retrieval_selection.json").read_text())["winner"]
                cfg = retrieval_select.config_from(winner)
            else:
                cfg = RetrievalConfig()
            if chunk_tokens:
                cfg = replace(cfg, chunk_tokens=chunk_tokens)
        try:
            result = retrieval_eval.evaluate(get_embedder(), cases, label=label, cfg=cfg, use_filters=filters)
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        except LLMError as exc:
            raise CommandError(f"Embedding failed ({exc.reason}); nothing was written.") from None
        j, m = retrieval_eval.save(result, cases)
        o = result["overall"]
        self.stdout.write(f"{label}: Recall@1 {o['recall@1']:.0%}, Recall@3 {o['recall@3']:.0%}, MRR {o['mrr']:.2f}, "
                          f"as shipped {o['shipped_hit_rate']:.0%}, false retrieval {o['false_retrieval_rate']:.0%}. "
                          f"Wrote {m.name}.")
