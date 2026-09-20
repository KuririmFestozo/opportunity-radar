from pathlib import Path
import ast


def test_full_discovery_disables_gupy_and_99jobs_known_page_stop():
    text = Path("main.py").read_text(encoding="utf-8")
    assert (
        'known_gupy = set() if (full_refresh or full_discovery) '
        'else store.known_ids("gupy_global")'
    ) in text
    assert (
        'known_99jobs = set() if (full_refresh or full_discovery) '
        'else store.known_ids("99jobs")'
    ) in text


def test_successfactors_html_query_is_not_trusted_by_default():
    text = Path("collectors/corporate_ats.py").read_text(encoding="utf-8")
    assert 'config.get("targeted_trust_html_query", False)' in text
    ast.parse(text)


def test_limit_messages_distinguish_job_and_page_guards():
    text = Path("collectors/corporate_ats.py").read_text(encoding="utf-8")
    assert "teto {cap_kind} de jobs={max_jobs} atingido" in text
    assert "query(s) atingiram" in text
