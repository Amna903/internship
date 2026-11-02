"""Week 5 Step 13 acceptance run with the real model (agent/agent_eval.py, evaluate_step13)."""

from django.conf import settings
from django.core.management.base import BaseCommand

from agent import agent_eval as step13
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = "Run the Step 13 acceptance evaluation and write assistant/eval/step13_acceptance.*"

    def handle(self, *args, **options):
        r = step13.evaluate_step13(get_llm(), get_embedder(), settings.ASSISTANT["SEED"])
        path = step13.save_step13(r)
        self.stdout.write(f"Gate: {'PASSED' if r['gate_passed'] else 'FAILED'} {r['gate']}. "
                          f"Injection retrieved and passed: {r['injection_retrieved_and_passed']}. Wrote {path.name}.")
