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
        parser.add_argument("--round2-winner", action="store_true",
                            help="Run the round-2 judge winner (assistant/dev/retrieval_round2.json) once (needs the model).")

    def handle(self, *args, label, selection_winner=False, chunk_tokens=None, filters=False, round2_winner=False, **options):
        if round2_winner:
            return self._round2(label)
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

    def _round2(self, label):
        import json
        from django.conf import settings
        from assistant import retrieval_round2
        from assistant.llm import get_llm
        winner = json.loads((retrieval_round2.OUT / "retrieval_round2.json").read_text())["winner"]
        if winner is None:
            raise CommandError("Round 2 has no winner to evaluate.")
        cases = retrieval_eval.load_cases()
        try:
            result = retrieval_eval.evaluate_judged(get_embedder(), get_llm(), cases, retrieval_round2.config_from(winner),
                                                    settings.ASSISTANT["SEED"], label=label)
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        retrieval_eval.save(result, cases)
        o = result["overall"]
        self.stdout.write(f"{label}: as shipped {o['shipped_hits']} of {o['answerable']}, false retrieval "
                          f"{o['false_retrievals']} of {o['unanswerable']}; judge calls {result['cost']['judge_calls']}.")
