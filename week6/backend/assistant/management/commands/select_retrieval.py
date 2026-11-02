"""Choose the retrieval setting on the dev set by the pre-written rules; optionally run the safety gate."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant import retrieval_select
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import LLMError, get_llm


class Command(BaseCommand):
    help = (
        "Dev-only retrieval selection (Step 3). With --safety-gate, also run the safety gate on a shipping challenger."
    )

    def add_arguments(self, parser):
        parser.add_argument("--safety-gate", action="store_true", help="Run the safety gate (needs the local model).")
        parser.add_argument("--admin", help="Admin recorded for the gate's U3b upload (required with --safety-gate).")

    def handle(self, *args, safety_gate=False, admin=None, **options):
        try:
            result = retrieval_select.select(get_embedder())
        except (CorpusMismatch, LLMError) as exc:
            raise CommandError(str(exc)) from None
        path = retrieval_select.save(result)
        d = result["decision"]
        self.stdout.write(
            f"{result['configurations']} configurations, {result['eligible']} eligible, best {result['best_hits']} "
            f"of {result['dev_answerable']} dev hits, {result['tied_at_top']} tied; champion "
            f"{result['champion_score']['hits']}. Challenger ships: {d['challenger_ships']} ({d['reason']}). "
            f"Wrote {path.name}."
        )
        if not safety_gate:
            return
        if not d["challenger_ships"]:
            self.stdout.write("No challenger to gate: the champion stays.")
            return
        actor = User.objects.filter(email=(admin or "").strip().lower(), role="admin").first()
        if actor is None:
            raise CommandError("--admin must name an admin account.")
        try:
            gate = safety_gate.run_gate(
                get_llm(),
                get_embedder(),
                actor,
                retrieval_select.config_from(result["winner"]),
                settings.ASSISTANT["SEED"],
            )
        except CorpusMismatch as exc:
            raise CommandError(str(exc)) from None
        out = safety_gate.save(gate)
        self.stdout.write(f"Safety gate {'PASSED' if gate['passed'] else 'FAILED'}. Wrote {out.name}.")
