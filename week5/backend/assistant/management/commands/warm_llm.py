"""Load the local model ahead of the first question, so its cold start doesn't hit a user's request."""

from django.core.management.base import BaseCommand, CommandError

from assistant.llm import LLMError, OllamaClient, get_llm


class Command(BaseCommand):
    help = "Load the assistant's local model into memory (avoids the cold-start delay on the first question)."

    def handle(self, *args, **options):
        llm = get_llm()
        if not isinstance(llm, OllamaClient):
            self.stdout.write("Provider is not Ollama; nothing to warm up.")
            return
        try:
            seconds = llm.warm_up()
        except LLMError as exc:
            raise CommandError(f"Could not reach the model: {exc.reason}") from None
        self.stdout.write(f"{llm.model} loaded in {seconds:.1f}s")
