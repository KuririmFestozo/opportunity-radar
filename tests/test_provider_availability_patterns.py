"""Provider-level status rules learned from actual posted/closed job pages."""
from datetime import date
import json

import pytest

from processing import source_availability as sa
from processing.rendered_availability import _private_host
from tools import full_availability_sweep as sweep


@pytest.mark.parametrize("source,text", [
    ("gupy_global", "Applications closed"),
    ("gupy_api", "Applications are closed"),
    ("successfactors", "Sorry, this position has been filled."),
    ("workday", "This position is no longer available."),
    ("greenhouse", "This job is no longer accepting applications."),
    ("lever", "This job is no longer available."),
    ("ashby", "This job has closed"),
    ("smartrecruiters", "This vacancy has been filled"),
    ("vagas_com", "Esta vaga não está mais disponível."),
    ("99jobs", "As inscrições foram encerradas."),
    ("iel", "O prazo de inscrições foi encerrado."),
    ("teamtailor", "This posting is no longer available."),
    ("ciee", "Vaga expirada."),
])
def test_source_independent_explicit_closed_banners(source, text):
    html = f"<main><div role='status'><span>{text}</span></div></main>"
    assert sa.classify_html(source, html)[0] == "closed"


@pytest.mark.parametrize("phrase", [
    "Applications closed",
    "This position has been filled",
    "Esta vaga não está mais disponível",
])
def test_no_false_positive_in_job_description_or_js(phrase):
    html = ("<main><h1>Engenheiro de Software</h1>"
            f"<p>Nosso sistema identifica a mensagem {phrase} em anúncios antigos.</p>"
            f"<script>const label = '{phrase}';</script>"
            "<p>Venha participar de nossa equipe.</p></main>")
    assert sa.classify_html("workday", html)[0] == "unverified"


def test_expired_jobposting_jsonld_with_explicit_valid_through():
    blob = json.dumps({
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Estágio - Laboratório",
        "validThrough": "2026-10-30T23:59:00-03:00",
    })
    html = f'<html><script type="application/ld+json">{blob}</script><p>Descrição da vaga.</p></html>'
    assert sa.classify_html("vagas_com", html, today=date(2026, 11, 6)) == (
        "closed", "jobposting_valid_through_2026-10-30"
    )


def test_jsonld_graph_can_contain_jobposting_and_unrelated_data():
    blob = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "validThrough": "2020-01-01"},
            {"@type": ["Thing", "JobPosting"], "validThrough": "2026-11-01"},
        ],
    })
    html = f'<script type="application/ld+json">{blob}</script>'
    assert sa.classify_html("gupy_global", html, today=date(2026, 11, 6))[0] == "closed"


def test_jsonld_non_jobposting_expired_does_not_close():
    blob = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "validThrough": "2020-01-01",
        "description": "Applications closed",
    })
    html = f'<script type="application/ld+json">{blob}</script>'
    assert sa.classify_html("vagas_com", html)[0] != "closed"


def test_jsonld_future_expiration_does_not_confirm_open():
    blob = json.dumps({
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "validThrough": "2099-12-31",
    })
    html = f'<script type="application/ld+json">{blob}</script>'
    assert sa.classify_html("vagas_com", html)[0] == "unverified"


@pytest.mark.parametrize("url,expected", [
    ("https://127.0.0.1/latest", True),
    ("http://example.com/job/1", True),
    ("https://169.254.169.254/latest", True),
    ("https://company.local/jobs/1", True),
    ("https://jobs.zf.com/job/123", False),
    ("https://belgo.gupy.io/job/1", False),
])
def test_browser_route_denies_local_or_non_https(url, expected):
    assert _private_host(url) is expected


def test_render_candidates_are_balanced_among_sources():
    jobs = [
        ("gupy_global", str(i), f"https://a.gupy.io/jobs/{i}")
        for i in range(15)
    ] + [
        ("successfactors", f"zf-{i}", f"https://jobs.zf.com/job/test/{i}/")
        for i in range(15)
    ]
    verdicts = {(source, job_id): ("unverified", "no_confirmed_application_state")
                for source, job_id, _ in jobs}
    choices = sweep._render_candidates(jobs, verdicts, limit=6)
    assert len(choices) == 6
    assert sum(source == "gupy_global" for source, _, _ in choices) == 3
    assert sum(source == "successfactors" for source, _, _ in choices) == 3


def test_render_candidates_never_revisit_closed_or_invalid_links():
    jobs = [
        ("gupy_global", "1", "https://a.gupy.io/jobs/1"),
        ("gupy_global", "2", "https://a.gupy.io/jobs/2"),
        ("gupy_global", "3", "http://127.0.0.1"),
    ]
    verdicts = {
        ("gupy_global", "1"): ("closed", "explicit_closed_message"),
        ("gupy_global", "2"): ("unverified", "no_readable_job_content"),
        ("gupy_global", "3"): ("unverified", "no_confirmed_application_state"),
    }
    assert sweep._render_candidates(jobs, verdicts, limit=10) == [jobs[1]]



def test_hidden_closed_banner_never_closes_public_job():
    html = """
      <main><h1>Estágio de Engenharia</h1>
      <div hidden><p>Applications closed</p></div>
      <section aria-hidden="true"><span>Vaga encerrada</span></section>
      <div style="display:none">This job has closed</div>
      <p>Candidaturas abertas para diversas posições.</p>
      </main>
    """
    assert sa.classify_html("gupy_global", html)[0] == "unverified"
