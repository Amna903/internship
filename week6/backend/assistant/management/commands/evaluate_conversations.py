"""Follow-up conversations and the history red-team on the frozen Week 5 corpus (Step 5). Needs the model."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant import conversation_eval
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Evaluate follow-ups and the history red-team; writes assistant/eval/conversation_eval.{json,md}."

    def handle(self, *args, **options):
        convs = conversation_eval.load_conversations()
        try:
            r = conversation_eval.evaluate(get_llm(), get_embedder(), settings.ASSISTANT["SEED"])
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        path = conversation_eval.save(r, convs)
        o = r["summary"]["overall"]
        self.stdout.write(f"Turn-2 hit: without history {o['hit_without']}/{o['answerable']}, with {o['hit_with']}/"
                          f"{o['answerable']}; key fact {o['key_fact_ok']}/{o['answerable']}; declined "
                          f"{o['abstained']}/{o['unanswerable']}")
        self.stdout.write("Red-team gate: " + ("PASSED" if r["gate_passed"] else "FAILED") + " ("
                          + ", ".join(f"{k} {'pass' if g['passed'] else 'FAIL'}" for k, g in r["gate"].items()) + ")")
        self.stdout.write(f"Wrote {path.name}.")
