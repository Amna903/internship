"""Step 3 round 2: choose an LLM-relevance-judge setting on the expanded dev set (needs the local model)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant import retrieval_round2, safety_gate
from assistant.documents import CorpusMismatch
from assistant.embeddings import get_embedder
from assistant.llm import LLMError, get_llm


class Command(BaseCommand):
    help = "Round-2 dev-only selection (LLM relevance judge). With --safety-gate, gate a shipping challenger."

    def add_arguments(self, parser):
        parser.add_argument("--safety-gate", action="store_true")
        parser.add_argument(
            "--gate-saved-winner",
            action="store_true",
            help="Run only the safety gate on the winner saved in assistant/dev/retrieval_round2.json "
            "(no new selection, so the gated winner is exactly the reported one).",
        )
        parser.add_argument("--admin", help="Admin recorded for the gate's U3b upload (required with --safety-gate).")

    def handle(self, *args, safety_gate=False, admin=None, gate_saved_winner=False, **options):
        if gate_saved_winner:
            import json

            saved = json.loads((retrieval_round2.OUT / "retrieval_round2.json").read_text())
            if not saved["decision"]["challenger_ships"]:
                raise CommandError("The saved round-2 result has no shipping challenger to gate.")
            return self._gate(saved, admin)
        try:
            r = retrieval_round2.select(get_embedder(), get_llm(), settings.ASSISTANT["SEED"])
        except (CorpusMismatch, LLMError) as exc:
            raise CommandError(str(exc)) from None
        path = retrieval_round2.save(r)
        d = r["decision"]
        self.stdout.write(
            f"{r['configurations']} configurations, {r['eligible']} eligible, best {r['best_hits']} of "
            f"{r['dev_answerable']} ({r['tied_at_top']} tied); champion {r['champion_score']['hits']} hits, "
            f"{r['champion_score']['false']} false; winner {r['winner_score']}; injection check "
            f"{'passed' if r['injection_check']['passed'] else 'FAILED'}. Ships: {d['challenger_ships']} "
            f"({d['reason']}). Wrote {path.name}."
        )
        if safety_gate and d["challenger_ships"]:
            self._gate(r, admin)

    def _gate(self, r, admin):
        actor = User.objects.filter(email=(admin or "").strip().lower(), role="admin").first()
        if actor is None:
            raise CommandError("--admin must name an admin account.")
        gate = safety_gate.run_gate(
            get_llm(), get_embedder(), actor, retrieval_round2.config_from(r["winner"]), settings.ASSISTANT["SEED"]
        )
        out = safety_gate.save(gate)
        self.stdout.write(f"Safety gate {'PASSED' if gate['passed'] else 'FAILED'}. Wrote {out.name}.")
