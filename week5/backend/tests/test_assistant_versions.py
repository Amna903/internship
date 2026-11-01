"""Week 5 Step 1 evidence (G1–G3, A5): document versions, update and delete re-indexing, metadata, citations
that name their edition, answer records, and evaluation runs that refuse a different corpus.
Offline: FakeEmbedder and FakeLLM throughout."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from assistant import documents, frozen, indexing
from assistant.documents import CorpusMismatch, DocumentError, check_corpus, corpus_snapshot
from assistant.embeddings import FakeEmbedder
from assistant.llm import FakeLLM, LLMUnavailable
from assistant.models import AnswerRecord, Chunk, DocumentVersion, PolicyDocument, passage_id
from audit.models import AuditEvent

from .conftest import Browser, user_login

DOCS = "/api/v1/assistant/documents/"
OLD = "A refund can be requested within 14 days of a payment."
NEW = "A refund can be requested within 30 days of a payment, in the patient app only."


def upload(browser, url, name, text, **fields):
    return browser.client.post(url, {"file": SimpleUploadedFile(name, text.encode()), **fields}, format="multipart",
                               **browser._csrf_headers())


def post(browser, url):
    return browser.client.post(url, **browser._csrf_headers())


def texts(question="refund days payment", top_k=10):
    return [p.text for p in indexing.search(question, FakeEmbedder(), top_k=top_k, floor=-1.0).passages]


@pytest.fixture
def policies(db, admin):
    call_command("load_policies", admin=admin.email)


@pytest.fixture
def live_doc(admin_browser):
    """An uploaded document whose v1 is approved and searchable."""
    doc_id = upload(admin_browser, DOCS, "refunds.md", OLD, policy_area="billing").json()["id"]
    assert post(admin_browser, f"{DOCS}{doc_id}/approve/").status_code == 200
    return doc_id


# ---------------- versions and atomic swap ----------------

@pytest.mark.django_db
class TestVersions:
    def test_new_version_is_pending_and_the_current_one_stays_searchable(self, admin_browser, live_doc):
        r = upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        assert r.status_code == 201 and r.json()["number"] == 2 and r.json()["status"] == "pending" and r.json()["chunks"] == 0
        assert OLD in texts() and NEW not in texts()

    def test_approving_an_update_swaps_editions_and_the_old_one_is_never_retrieved(self, admin_browser, live_doc):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        body = post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/").json()
        assert body["current_version"] == 2 and body["pending_version"] is None
        assert NEW in texts() and OLD not in texts()
        assert not Chunk.objects.filter(version__number=1, document_id=live_doc).exists()
        history = admin_browser.get(f"{DOCS}{live_doc}/versions/").json()["versions"]
        assert [(v["number"], v["status"]) for v in history] == [(1, "superseded"), (2, "current")]
        assert DocumentVersion.objects.get(document_id=live_doc, number=1).content == OLD  # kept for audit

    def test_failed_embedding_leaves_the_old_edition_live_and_the_new_one_pending(self, admin_browser, live_doc, monkeypatch):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)

        class Down(FakeEmbedder):
            def embed(self, texts):
                raise LLMUnavailable("down")
        monkeypatch.setattr("assistant.views.get_embedder", lambda: Down())
        assert post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/").status_code == 503
        assert OLD in texts() and NEW not in texts()
        assert DocumentVersion.objects.get(document_id=live_doc, number=2).status == "pending"

    def test_a_version_decided_while_embedding_is_not_approved_twice(self, admin, live_doc, admin_browser):
        """The pending check is repeated inside the locked transaction, after the slow embedding."""
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        version = DocumentVersion.objects.get(document_id=live_doc, number=2)

        class RacingEmbedder(FakeEmbedder):
            def embed(self, texts):
                documents.reject_version(version, admin)  # another admin decides meanwhile
                return super().embed(texts)
        with pytest.raises(DocumentError, match="waiting for approval"):
            documents.approve_version(version, admin, RacingEmbedder())
        assert OLD in texts() and NEW not in texts()

    def test_approval_takes_the_document_row_lock(self, admin, live_doc, admin_browser, monkeypatch):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        locked = []
        real = PolicyDocument.objects.select_for_update
        monkeypatch.setattr(PolicyDocument.objects, "select_for_update", lambda *a, **k: locked.append(1) or real(*a, **k))
        documents.approve_version(DocumentVersion.objects.get(document_id=live_doc, number=2), admin, FakeEmbedder())
        assert locked

    def test_reject_keeps_the_version_and_never_indexes_it(self, admin_browser, live_doc):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        assert post(admin_browser, f"{DOCS}{live_doc}/versions/2/reject/").json()["status"] == "rejected"
        assert post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/").status_code == 409
        assert OLD in texts() and NEW not in texts()

    @pytest.mark.parametrize("text, code", [(OLD, "duplicate_document")])
    def test_an_update_identical_to_the_current_text_is_refused(self, admin_browser, live_doc, text, code):
        r = upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", text)
        assert r.status_code == 409 and r.json()["error"]["code"] == code

    def test_only_one_pending_version_at_a_time(self, admin_browser, live_doc):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        r = upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW + " Also by post.")
        assert r.status_code == 409 and r.json()["error"]["code"] == "version_pending"

    def test_audit_records_ids_and_versions_only(self, admin_browser, live_doc):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/")
        details = list(AuditEvent.objects.order_by("id").values_list("action", "detail"))
        assert ("admin.document_version_uploaded", f"document:{live_doc}:v2") in details
        assert ("admin.document_approved", f"document:{live_doc}:v2:from_v1") in details
        assert not any("refund" in (d or "") for _, d in details)


# ---------------- retire (soft delete) ----------------

@pytest.mark.django_db
class TestRetire:
    def test_retired_document_leaves_search_but_keeps_its_versions(self, admin_browser, live_doc):
        body = post(admin_browser, f"{DOCS}{live_doc}/retire/").json()
        assert body["status"] == "retired" and body["chunks"] == 0
        assert OLD not in texts() and DocumentVersion.objects.filter(document_id=live_doc).count() == 1
        assert AuditEvent.objects.filter(action="admin.document_retired", detail=f"document:{live_doc}").exists()
        assert post(admin_browser, f"{DOCS}{live_doc}/retire/").status_code == 409

    def test_restoring_means_a_new_version_and_approval(self, admin_browser, live_doc):
        post(admin_browser, f"{DOCS}{live_doc}/retire/")
        assert upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW).status_code == 201
        assert NEW not in texts()  # pending: still not searchable
        body = post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/").json()
        assert body["status"] == "approved" and NEW in texts() and OLD not in texts()

    def test_retired_seed_policies_free_their_text_for_a_new_upload(self, admin_browser, policies):
        billing = PolicyDocument.objects.get(filename="billing.md")
        post(admin_browser, f"{DOCS}{billing.id}/retire/")
        content = billing.current_version.content
        assert upload(admin_browser, DOCS, "billing-copy.md", content).status_code == 201


# ---------------- metadata and input checks ----------------

@pytest.mark.django_db
class TestMetadata:
    def test_seed_policies_get_their_area_from_the_filename(self, policies):
        assert dict(PolicyDocument.objects.values_list("filename", "policy_area")) == {
            f"{a}.md": a for a in ["billing", "cancellation", "privacy", "reminders", "rescheduling", "telehealth"]}

    def test_upload_without_an_area_defaults_to_other_so_the_week4_contract_holds(self, admin_browser):
        assert upload(admin_browser, DOCS, "misc.md", "Parking is free.").json()["policy_area"] == "other"

    @pytest.mark.parametrize("fields, message", [({"policy_area": "medical"}, "policy_area"),
                                                 ({"effective_date": "next tuesday"}, "effective_date"),
                                                 ({"owner": "x"}, "Unknown fields")])
    def test_bad_metadata_is_refused(self, admin_browser, fields, message):
        r = upload(admin_browser, DOCS, "misc.md", "Parking is free.", **fields)
        assert r.status_code == 400 and message in r.json()["error"]["message"]

    def test_effective_date_is_stored_on_the_version(self, admin_browser, live_doc):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW, effective_date="2026-12-01")
        assert str(DocumentVersion.objects.get(document_id=live_doc, number=2).effective_date) == "2026-12-01"

    def test_a_version_cannot_change_the_area(self, admin_browser, live_doc):
        r = upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW, policy_area="privacy")
        assert r.status_code == 400

    def test_upload_checks_from_week4_still_apply_to_versions(self, admin_browser, live_doc):
        r = admin_browser.client.post(f"{DOCS}{live_doc}/versions/", {"file": SimpleUploadedFile("x.pdf", b"%PDF-1.7")},
                                      format="multipart", **admin_browser._csrf_headers())
        assert r.status_code == 400 and r.json()["error"]["code"] == "upload_rejected"


@pytest.mark.django_db
class TestPermissions:
    @pytest.mark.parametrize("method, path", [("get", "1/versions/"), ("post", "1/versions/"), ("post", "1/versions/2/approve/"),
                                              ("post", "1/versions/2/reject/"), ("post", "1/retire/")])
    def test_anonymous_and_members_are_refused(self, browser, user, method, path):
        assert getattr(browser.client, method)(DOCS + path).status_code in (401, 403)
        member = Browser()
        user_login(member, user.email)
        assert getattr(member.client, method)(DOCS + path, **member._csrf_headers()).status_code in (401, 403)

    def test_writes_need_the_csrf_token(self, admin_browser, live_doc):
        assert admin_browser.client.post(f"{DOCS}{live_doc}/retire/").status_code == 403
        assert PolicyDocument.objects.get(pk=live_doc).status == "approved"

    @pytest.mark.parametrize("path", ["999/versions/", "999/retire/", "999/versions/1/approve/", "999/versions/1/reject/"])
    def test_unknown_ids_are_404(self, admin_browser, path):
        r = post(admin_browser, DOCS + path) if not path.endswith("versions/") else admin_browser.get(DOCS + path)
        assert r.status_code == 404


# ---------------- citations name their edition; answer records ----------------

def reply(passage, quote):
    return json.dumps({"answer": "A refund can be requested within 30 days of a payment, in the patient app.",
                       "citations": [{"passage_id": passage, "quote": quote}], "refused": False})


@pytest.mark.django_db
class TestEditionsInAnswers:
    def test_passage_ids_keep_week4_form_for_v1_and_name_later_editions(self):
        assert passage_id("billing.md", 1, 0) == "billing.md#0"
        assert passage_id("billing.md", 2, 0) == "billing.md@v2#0"

    def test_seed_policies_keep_their_week4_passage_ids(self, policies):
        ids = {c.passage_id for c in Chunk.objects.select_related("document", "version")}
        assert "billing.md#0" in ids and not any("@v" in i for i in ids)

    def test_answer_citations_and_record_name_the_edition(self, admin_browser, live_doc, monkeypatch):
        upload(admin_browser, f"{DOCS}{live_doc}/versions/", "refunds.md", NEW)
        post(admin_browser, f"{DOCS}{live_doc}/versions/2/approve/")
        fake = FakeLLM()
        fake.replies.append(reply("refunds.md@v2#0", NEW))
        monkeypatch.setattr("assistant.views.get_llm", lambda: fake)
        monkeypatch.setattr("assistant.answering.load_tuned", lambda: {"floor": 0.0, "top_k": 3, "groundedness_threshold": 0.3})
        body = admin_browser.post("/api/v1/assistant/ask/", {"question": "How many days do I have to request a refund?"}).json()
        assert body["status"] == "answered", body
        assert body["citations"][0]["passage_id"] == "refunds.md@v2#0" and body["citations"][0]["version"] == 2
        record = AnswerRecord.objects.get()
        sha = DocumentVersion.objects.get(document_id=live_doc, number=2).sha256
        assert record.citations == [{"passage_id": "refunds.md@v2#0", "document_id": live_doc, "version": 2, "sha256": sha}]
        assert record.audit_event.action == "admin.assistant_asked"
        assert "refund" not in json.dumps(record.citations + record.sources).replace("refunds.md", "")

    def test_every_answer_gets_a_record_even_without_citations(self, admin_browser, policies, monkeypatch):
        monkeypatch.setattr("assistant.views.get_llm", lambda: FakeLLM())
        admin_browser.post("/api/v1/assistant/ask/", {"question": "Which medicine should I take for my fever?"})
        record = AnswerRecord.objects.get()
        assert record.status == "refused" and record.citations == [] and record.sources == []


# ---------------- corpus snapshot: evaluations refuse a different corpus ----------------

@pytest.mark.django_db
class TestCorpusSnapshot:
    def test_the_week4_corpus_is_the_six_frozen_policies_as_v1(self, policies):
        snapshot = check_corpus(frozen.WEEK4_CORPUS)
        assert [(r["filename"], r["version"]) for r in snapshot] == [(n, 1) for n in sorted(frozen.WEEK4_CORPUS)]

    def test_an_updated_policy_fails_loudly(self, policies, admin):
        billing = PolicyDocument.objects.get(filename="billing.md")
        documents.approve_version(documents.add_version(billing, NEW, "f" * 64, admin), admin, FakeEmbedder())
        with pytest.raises(CorpusMismatch, match="changed: billing.md expected v1"):
            check_corpus(frozen.WEEK4_CORPUS)

    def test_an_extra_searchable_document_fails_loudly(self, policies, admin):
        doc = documents.create_document("extra.md", "Parking is free.", "e" * 64, "upload", admin)
        documents.approve(doc, admin, FakeEmbedder())
        with pytest.raises(CorpusMismatch, match="not expected: extra.md"):
            check_corpus(frozen.WEEK4_CORPUS)

    def test_a_retired_policy_fails_loudly(self, policies, admin):
        documents.retire(PolicyDocument.objects.get(filename="privacy.md"), admin)
        with pytest.raises(CorpusMismatch, match="missing: privacy.md"):
            check_corpus(frozen.WEEK4_CORPUS)

    def test_a_pending_upload_does_not_count(self, policies, admin):
        documents.create_document("extra.md", "Parking is free.", "e" * 64, "upload", admin)
        check_corpus(frozen.WEEK4_CORPUS)

    def test_the_evaluation_command_refuses_before_running_any_case(self, policies, admin, monkeypatch):
        documents.retire(PolicyDocument.objects.get(filename="privacy.md"), admin)
        monkeypatch.setattr("assistant.evaluate.run_case", lambda *a, **k: pytest.fail("no case may run"))
        with pytest.raises(CommandError, match="differ from the corpus"):
            call_command("evaluate_assistant", admin=admin.email)

    def test_the_tuning_command_refuses_too(self, policies, admin, monkeypatch):
        documents.retire(PolicyDocument.objects.get(filename="privacy.md"), admin)
        monkeypatch.setattr("assistant.tuning.run_once", lambda *a, **k: pytest.fail("no dev question may run"))
        with pytest.raises(CommandError, match="differ from the corpus"):
            call_command("tune_assistant")

    def test_evaluation_results_record_the_snapshot(self, policies, admin, monkeypatch):
        from assistant import evaluate
        monkeypatch.setattr(evaluate, "run_case", lambda *a, **k: {"status": "x"})
        result = evaluate.evaluate(FakeLLM(), FakeEmbedder(), admin, 42)
        assert result["corpus"] == corpus_snapshot() and len(result["corpus"]) == 6


# ---------------- data migration ----------------

@pytest.mark.django_db(transaction=True)
def test_migration_moves_week4_documents_into_v1_and_back(admin):
    executor = MigrationExecutor(connection)
    executor.migrate([("assistant", "0001_initial")])
    apps = executor.loader.project_state([("assistant", "0001_initial")]).apps
    OldDoc, OldChunk = apps.get_model("assistant", "PolicyDocument"), apps.get_model("assistant", "Chunk")
    doc = OldDoc.objects.create(filename="billing.md", sha256="a" * 64, content="Refunds within 14 days.",
                                status="approved", source="seed")
    pending = OldDoc.objects.create(filename="notes.md", sha256="b" * 64, content="Draft.", status="pending", source="upload")
    OldChunk.objects.create(document=doc, position=0, text="Refunds within 14 days.", embedding=b"\x00" * 8,
                            embedding_model="fake-hash/v1")

    executor = MigrationExecutor(connection)
    executor.migrate([("assistant", "0004_answerrecord")])
    apps = executor.loader.project_state([("assistant", "0004_answerrecord")]).apps
    Doc, Version, Chunk_ = (apps.get_model("assistant", n) for n in ("PolicyDocument", "DocumentVersion", "Chunk"))
    billing = Doc.objects.get(pk=doc.pk)
    v1 = Version.objects.get(document=billing)
    assert (v1.number, v1.status, v1.content, v1.sha256) == (1, "current", "Refunds within 14 days.", "a" * 64)
    assert billing.current_version_id == v1.pk and billing.policy_area == "billing"
    assert Chunk_.objects.get(document=billing).version_id == v1.pk  # same chunk, not re-embedded
    assert Version.objects.get(document_id=pending.pk).status == "pending"
    assert Doc.objects.get(pk=pending.pk).current_version_id is None

    executor = MigrationExecutor(connection)
    executor.migrate([("assistant", "0001_initial")])
    apps = executor.loader.project_state([("assistant", "0001_initial")]).apps
    back = apps.get_model("assistant", "PolicyDocument").objects.get(pk=doc.pk)
    assert (back.content, back.sha256, back.status) == ("Refunds within 14 days.", "a" * 64, "approved")

    MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
