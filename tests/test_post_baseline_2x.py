from pathlib import Path
import ast


def test_full_discovery_and_daily_audit_disable_gupy_and_99jobs_known_page_stop():
    text = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(text)

    # Known discovery IDs are retained so cached/source state is reusable.
    discovery_sources = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "known_discovery_ids"
            and isinstance(func.value, ast.Name)
            and func.value.id == "store"
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            discovery_sources.add(node.args[0].value)

    assert {"gupy_global", "99jobs"} <= discovery_sources

    # Both FULL_DISCOVERY and DAILY_AUDIT disable known-page early-stop.
    assert '0 if (full_discovery or daily_audit) else 2' in text
    assert 'full_discovery or daily_audit' in text
    assert 'else (3 if known_99jobs else 0)' in text


def test_successfactors_html_query_is_not_trusted_by_default():
    text = Path("collectors/corporate_ats.py").read_text(encoding="utf-8")
    assert 'config.get("targeted_trust_html_query", False)' in text
    ast.parse(text)


def test_limit_messages_distinguish_job_and_page_guards():
    text = Path("collectors/corporate_ats.py").read_text(encoding="utf-8")
    assert "teto {cap_kind} de jobs={max_jobs} atingido" in text
    assert "query(s) atingiram" in text
