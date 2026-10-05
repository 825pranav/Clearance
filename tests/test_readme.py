"""Every eval number quoted in the README must match evals/results.json."""

import json

from app import config


def test_readme_numbers_match_results_json():
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    results = json.loads((config.ROOT / "evals" / "results.json").read_text(encoding="utf-8"))
    main, adv = results["main"], results["adversarial"]

    expected = [
        f"**Main suite: {main['passed']}/{main['total']} passed, {main['safety_violations']} safety violations.**",
        f"{main['avg_seconds_per_reply']} s per reply on average, {main['avg_llm_calls_per_case']} LLM calls per case",
        f"**Adversarial suite: harm {adv['harm']}/{adv['total']}, fooled {adv['fooled']}/{adv['total']}.**",
        f"**Retrieval: {results['retrieval']['hits']}/{results['retrieval']['total']}**",
        f"**{results['consistency']['same_all_runs']}/{results['consistency']['total']}** cases",
    ]
    names = {"clear": "clear request", "vague": "vague, then details", "baseline": "covered by role baseline",
             "duplicate": "duplicate of open/approved request", "high_risk": "high risk", "policy": "policy question",
             "adversarial": "adversarial"}
    expected += [f"| {names[c]} | {b['passed']}/{b['total']} |" for c, b in main["by_category"].items()]
    adv_names = {"direct_override": "direct override", "false_authority": "false authority",
                 "impersonation": "impersonation", "poisoned_document": "poisoned document"}
    expected += [f"| {adv_names[c]} | {b['fooled']}/{b['total']} | {b['harm']}/{b['total']} |"
                 for c, b in adv["by_category"].items()]
    missing = [line for line in expected if line not in readme]
    assert not missing, missing


def test_design_doc_numbers_match_results_json():
    design = (config.ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    results = json.loads((config.ROOT / "evals" / "results.json").read_text(encoding="utf-8"))
    main, adv = results["main"], results["adversarial"]
    for text in (f"**{main['passed']}/{main['total']}**, {main['safety_violations']} safety violations",
                 f"{main['avg_seconds_per_reply']} s per reply, {main['avg_llm_calls_per_case']} LLM calls per case",
                 f"**fooled {adv['fooled']}/{adv['total']}, harm {adv['harm']}/{adv['total']}**",
                 f"{results['retrieval']['hits']}/{results['retrieval']['total']} expected file in top 3"):
        assert text in design, text
