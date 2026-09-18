import json
from pathlib import Path
import shutil
import subprocess

import pytest

from models.job import Job
from models.profile import SearchProfile
from processing.matching import match_job


ROOT = Path(__file__).resolve().parents[1]


def run_dashboard(jobs, preset, scenario, *, omit_matches=()):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute dashboard JavaScript regression tests")
    data = {
        "jobs": [j.to_dict() for j in jobs], "profiles": [preset.to_dict()],
        "matches": [match_job(j, preset).to_dict() for j in jobs if j.source_job_id not in omit_matches],
        "courses": {key: {"label": key} for key in preset.course_ids},
        "intents": {key: {"label": key} for key in preset.intent_ids},
        "stats": {}, "search_links": [],
    }
    payload = dict(html=(ROOT / "web/dashboard.html").read_text(encoding="utf-8"), data=data,
                   scenario=scenario)
    result = subprocess.run(
        [node, str(ROOT / "tests/dashboard_harness.js")],
        input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True,
        check=True, timeout=15,
    )
    return json.loads(result.stdout)


def job(identifier, **overrides):
    values = dict(source="test", source_job_id=identifier, company="Empresa",
                  title=identifier, location="", url=f"https://example.com/{identifier}",
                  course_scores={"computer_science": 90})
    values.update(overrides)
    return Job(**values)


def profile(**overrides):
    values = dict(id="preset", name="Preset", course_ids=["computer_science"],
                  intent_ids=[], minimum_score=45)
    values.update(overrides)
    return SearchProfile(**values)


SELECT_PROFILE = 'profileEl.value="preset"; applyProfile(); render();'


def test_dashboard_profile_uses_eligibility_and_explore_keeps_every_job():
    result = run_dashboard([
        job("eligible"), job("excluded", description="Vendas"), job("unmatched"),
    ], profile(exclude_keywords=["vendas"]), SELECT_PROFILE + '''
        const selected=$('jobs').innerHTML;
        resetFilters();
        ({selected, explore:$('jobs').innerHTML});
    ''', omit_matches={"unmatched"})
    assert 'https://example.com/eligible' in result["selected"]
    assert 'https://example.com/excluded' not in result["selected"]
    assert 'https://example.com/unmatched' not in result["selected"]
    for identifier in ("eligible", "excluded", "unmatched"):
        assert f'https://example.com/{identifier}' in result["explore"]


def test_dashboard_multi_course_profile_keeps_second_course_match():
    result = run_dashboard([
        job("data", course_scores={"computer_science": 0, "data_science": 90}),
        job("neither", course_scores={"computer_science": 0, "data_science": 0}),
    ], profile(course_ids=["computer_science", "data_science"]), SELECT_PROFILE + '''
        ({html:$('jobs').innerHTML, course:courseEl.value});
    ''')
    assert 'https://example.com/data' in result["html"]
    assert 'https://example.com/neither' not in result["html"]
    assert result["course"] == ""


@pytest.mark.parametrize("minimum", [40, 45, 47])
def test_dashboard_represents_exact_preset_minimum(minimum):
    result = run_dashboard([
        job("ok"), job("boundary", course_scores={"computer_science": 60}),
    ], profile(minimum_score=minimum), SELECT_PROFILE + '''
        ({score:$('score').value, options:$('score').options.map(o=>o.value), html:$('jobs').innerHTML});
    ''')
    assert result["score"] == str(minimum)
    assert result["options"].count(str(minimum)) == 1
    assert ('https://example.com/boundary' in result["html"]) == (minimum == 40)


def test_dashboard_does_not_reinterpret_backend_keyword_rules():
    result = run_dashboard([
        job("partial", description="Revendas"), job("excluded", description="SÊNIOR"),
    ], profile(exclude_keywords=["vendas", "senior"], include_keywords=["python"]),
        SELECT_PROFILE + "$('jobs').innerHTML;")
    assert 'https://example.com/partial' in result
    assert 'https://example.com/excluded' not in result


def test_dashboard_keeps_backend_intent_and_location_compatibility():
    result = run_dashboard([
        job("coop", detected_intents=["co_op"]),
        job("summer", detected_intents=["summer_internship"]),
        job("wrong-intent", detected_intents=["trainee"]),
    ], profile(intent_ids=["internship"], preferred_countries=["BR"],
               max_distance_km=50, allow_unknown_distance=True),
        SELECT_PROFILE + "$('jobs').innerHTML;")
    assert 'https://example.com/coop' in result
    assert 'https://example.com/summer' in result
    assert 'https://example.com/wrong-intent' not in result


def test_dashboard_interface_filters_still_apply_in_explore():
    result = run_dashboard([
        job("data", course_scores={"computer_science": 0, "data_science": 90}),
        job("cs", course_scores={"computer_science": 90, "data_science": 0}),
    ], profile(course_ids=["computer_science", "data_science"]), SELECT_PROFILE + '''
        courseEl.value='data_science';
        courseEl.listeners.change();
        ({html:$('jobs').innerHTML, profile:profileEl.value});
    ''')
    assert result["profile"] == "__explore__"
    assert 'https://example.com/data' in result["html"]
    assert 'https://example.com/cs' not in result["html"]


def test_lowering_ui_minimum_cannot_make_ineligible_job_match_profile():
    result = run_dashboard([
        job("low", course_scores={"computer_science": 60}),
        job("high"),
    ], profile(minimum_score=45), SELECT_PROFILE + '''
        $('score').value='0'; render(); $('jobs').innerHTML;
    ''')
    assert 'https://example.com/low' not in result
    assert 'https://example.com/high' in result
