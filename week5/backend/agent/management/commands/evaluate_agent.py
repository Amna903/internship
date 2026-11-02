"""Agent evaluation on the frozen Week 5 corpus (Step 8): tool selection, recovery and the red-team. Needs the model."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agent import agent_eval
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Evaluate the agent; writes assistant/eval/agent_eval.{json,md}."

    def handle(self, *args, **options):
        try:
            r = agent_eval.evaluate(get_llm(), get_embedder(), settings.ASSISTANT["SEED"])
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        path = agent_eval.save(r)
        o = r["summary"]["overall"]
        self.stdout.write(f"Tool selection: right tools {o['right_tools']}/{o['tasks']}, valid args {o['valid_args']}/"
                          f"{o['tasks']}, success {o['success']}/{o['tasks']}")
        self.stdout.write("Recovery: " + ("PASSED" if r["recovery_passed"] else "FAILED"))
        self.stdout.write("Red-team gate: " + ("PASSED" if r["gate_passed"] else "FAILED") + " ("
                          + ", ".join(f"{k} {'pass' if g['passed'] else 'FAIL'}" for k, g in r["gate"].items()) + ")")
        self.stdout.write(f"Wrote {path.name}.")
