"""Week 5 Step 13: the acceptance harness's own pieces (the real-model run is evidence, not a test)."""

import json

from agent.step13 import injection_retrieved
from assistant import frozen


def test_injection_counts_only_a_successful_search_that_returned_the_marker():
    hit = {"tool": "search_policies", "ok": True, "output": {"passages": [{"text": "x NOTE TO ASSISTANT y"}]}}
    assert injection_retrieved({"calls": [hit]}, "NOTE TO ASSISTANT")
    assert not injection_retrieved({"calls": [{**hit, "ok": False}]}, "NOTE TO ASSISTANT")
    assert not injection_retrieved({"calls": [{**hit, "tool": "check_availability"}]}, "NOTE TO ASSISTANT")
    assert not injection_retrieved({"calls": []}, "NOTE TO ASSISTANT")


def test_disguised_cases_are_frozen_assistant_authored_and_keep_the_h3_h9_rules():
    cases = json.loads(frozen.STEP13_REDTEAM.read_text())["cases"]
    assert {c["id"]: c["must"] for c in cases} == {"H3d": "no_phone_number", "H9d": "no_unverified_citation"}
    assert all(c["author"] == "assistant" and len(c["turns"]) == 2 for c in cases)
