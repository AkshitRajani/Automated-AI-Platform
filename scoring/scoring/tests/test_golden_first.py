"""Golden-first scoring: efficient suites beat padded mimicry; agent assist mocked."""
from __future__ import annotations

from scoring.coverage_assist import CoverageAssistResult, run_coverage_assist
from scoring.models import Scenario, Step
from scoring.score import score


def _scenario(
    name: str,
    when: str,
    then: str,
    *,
    feature: str = "app.feature",
    feature_name: str = "App",
    given: str = "an account exists",
) -> Scenario:
    return Scenario(
        feature_file=feature,
        feature_name=feature_name,
        name=name,
        steps=(
            Step("Given", given),
            Step("When", when),
            Step("Then", then),
        ),
    )


def _manual_suite() -> list[Scenario]:
    return [
        _scenario(
            "Late fee when payment is overdue",
            "the late fee job runs",
            "a 5% late fee is applied to the balance",
            given="an account with payment due 20 days ago",
        ),
        _scenario(
            "No late fee within grace period",
            "the late fee job runs",
            "no late fee is applied to the balance",
            given="an account with payment due 5 days ago",
        ),
        _scenario(
            "Fee waived for admin override",
            "the admin waives the late fee",
            "the account balance has no late fee charge",
            feature="admin.feature",
            feature_name="Admin overrides",
            given="an overdue account",
        ),
    ]


def test_efficient_suite_beats_padded_suite(monkeypatch):
    """Lean coverage of golden beats many padded extras that do not cover more manuals."""
    monkeypatch.setenv("SCORING_PROFILING_MODE", "regex")
    manual = _manual_suite()
    lean = list(manual)
    padded = list(manual) + [
        _scenario(
            f"Unrelated help page {i}",
            "the user opens the help page",
            "the help documentation is shown",
            feature=f"noise_{i}.feature",
            feature_name="Noise",
            given="a signed in user",
        )
        for i in range(12)
    ]

    lean_report = score(manual, lean, threshold=0.45, profiling_mode="regex")
    pad_report = score(manual, padded, threshold=0.45, profiling_mode="regex")

    assert lean_report.breakdown.manual_recall_pct == 100.0
    assert pad_report.breakdown.manual_recall_pct == 100.0
    assert lean_report.breakdown.coverage_efficiency_pct > pad_report.breakdown.coverage_efficiency_pct
    assert lean_report.breakdown.suite_precision_pct > pad_report.breakdown.suite_precision_pct
    assert lean_report.breakdown.overall_score > pad_report.breakdown.overall_score


def test_perfect_match_still_scores_high_golden_first(monkeypatch):
    monkeypatch.setenv("SCORING_PROFILING_MODE", "regex")
    manual = _manual_suite()
    report = score(manual, list(manual), threshold=0.45, profiling_mode="regex")
    assert report.breakdown.manual_recall_pct == 100.0
    assert report.breakdown.suite_precision_pct == 100.0
    assert report.breakdown.coverage_efficiency_pct == 100.0
    assert report.breakdown.overall_score >= 90.0
    assert "golden_first" in report.breakdown.scoring_mode
    assert "golden-first" in report.breakdown.explanation[0].lower()


def test_coverage_assist_noop_in_regex(monkeypatch):
    monkeypatch.setenv("SCORING_PROFILING_MODE", "regex")
    from scoring.behavior import profile_scenario_regex

    manual = _manual_suite()
    profiles = [profile_scenario_regex(s) for s in manual]
    result = run_coverage_assist(
        manual_profiles=profiles,
        gen_profiles=profiles,
        matches=[],
        missing=[],
        profiling_mode="regex",
    )
    assert not result.credited_manual_scenarios
    assert not result.redundant_generated_scenarios


def test_coverage_assist_mocked_credits_and_redundancy(monkeypatch):
    monkeypatch.setenv("SCORING_PROFILING_MODE", "agent")
    from scoring.behavior import profile_scenario_regex

    manual = _manual_suite()
    profiles = [profile_scenario_regex(s) for s in manual]
    gen_extra = profile_scenario_regex(
        _scenario(
            "Duplicate late fee check",
            "the late fee job runs",
            "a 5% late fee is applied to the balance",
            given="an account with payment due 20 days ago",
        )
    )

    def fake_invoke(unmatched, candidates):
        assert unmatched
        return {
            "credits": [
                {
                    "manual_scenario": unmatched[0].scenario,
                    "covering_generated_scenario": candidates[0].scenario,
                    "covers": True,
                    "why": "mock many-to-one",
                }
            ],
            "redundant_generated": ["Duplicate late fee check"],
        }

    result = run_coverage_assist(
        manual_profiles=profiles,
        gen_profiles=profiles + [gen_extra],
        matches=[],
        missing=[],  # unused by assist when unmatched derived from matches
        profiling_mode="agent",
        invoke_fn=fake_invoke,
    )
    credited = set(result.credited_manual_scenarios)
    assert credited
    assert credited.issubset({p.scenario for p in profiles})
    assert "Duplicate late fee check" in result.redundant_generated_scenarios


def test_score_applies_assist_credits_to_recall(monkeypatch):
    """When assist credits an unmatched manual, recall rises without inventing 1:1 matches."""
    import importlib

    monkeypatch.setenv("SCORING_PROFILING_MODE", "regex")
    manual = _manual_suite()
    generated = [manual[0]]

    score_mod = importlib.import_module("scoring.score")

    baseline = score_mod.score(manual, generated, threshold=0.45, profiling_mode="regex")
    assert baseline.breakdown.manual_recall_pct < 100.0
    baseline_matched = baseline.matched_behaviors

    credited = {manual[1].name, manual[2].name}

    def fake_assist(**_kwargs):
        return CoverageAssistResult(
            credited_manual_scenarios=set(credited),
            notes=["mock assist credited manuals"],
        )

    monkeypatch.setattr(score_mod, "run_coverage_assist", fake_assist)
    assisted = score_mod.score(manual, generated, threshold=0.45, profiling_mode="regex")

    assert assisted.matched_behaviors == baseline_matched
    assert assisted.breakdown.agent_credited_manual_count == 2
    assert assisted.breakdown.manual_recall_pct == 100.0
    assert baseline.breakdown.manual_recall_pct < assisted.breakdown.manual_recall_pct
    assert any("mock assist" in line for line in assisted.breakdown.explanation)
