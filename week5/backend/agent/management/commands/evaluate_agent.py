"""Agent evaluation on the frozen Week 5 corpus (Step 8): tool selection, recovery and the red-team. Needs the model."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agent import agent_eval
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import get_llm


class Command(BaseCommand):
    help = ("Evaluate the agent. Default: round 1 (assistant/eval/agent_eval.*). --dev: the round-2 dev set "
            "(agent/dev/agent_dev.md). --round2: the frozen sets again plus the fresh holdout (assistant/eval/agent_eval_round2.*).")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--dev", action="store_true")
        group.add_argument("--round2", action="store_true")

    def handle(self, *args, **options):
        llm, embedder, seed = get_llm(), get_embedder(), settings.ASSISTANT["SEED"]
        try:
            if options["dev"]:
                r = agent_eval.evaluate_dev(llm, embedder, seed)
                path = agent_eval.save_dev(r)
                o = r["summary"]["overall"]
                self.stdout.write(f"Dev: right tools {o['right_tools']}/{o['tasks']}, valid args {o['valid_args']}/{o['tasks']}, "
                                  f"success {o['success']}/{o['tasks']}. Wrote {path.name}.")
                return
            if options["round2"]:
                r = agent_eval.evaluate_round2(llm, embedder, seed)
                path = agent_eval.save_round2(r)
                for key in ("holdout", "second_run"):
                    o = r[key]["summary"]["overall"]
                    self.stdout.write(f"{r[key]['label']}: success {o['success']}/{o['tasks']}, gate "
                                      f"{'PASSED' if r[key]['gate_passed'] else 'FAILED'}")
                self.stdout.write(f"Gate on both: {'PASSED' if r['gate_passed'] else 'FAILED'}. Wrote {path.name}.")
                return
            r = agent_eval.evaluate(llm, embedder, seed)
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
