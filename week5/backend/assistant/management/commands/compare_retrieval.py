"""Write the Step 3 before/after report from the saved retrieval runs (no model, no database changes)."""

import json

from django.core.management.base import BaseCommand

from assistant import retrieval_eval, retrieval_select


class Command(BaseCommand):
    help = "Write assistant/eval/retrieval_before_after.md from the saved baseline, after, chunk-size and filter runs."

    def handle(self, *args, **options):
        selection = json.loads((retrieval_select.OUT / "retrieval_selection.json").read_text())
        path = retrieval_eval.OUT / "retrieval_before_after.md"
        path.write_text(retrieval_eval.compare_report(selection))
        self.stdout.write(f"Wrote {path.name}.")
