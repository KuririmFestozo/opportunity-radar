from models.job import Job
from processing.classification import classify_job
from processing.collection_planner import build_collection_queries

br_summer = Job(
    source="test",
    source_job_id="1",
    company="Hyundai",
    title="Programa de Estágio de Verão 2027",
    location="Piracicaba - SP",
    url="https://example.com/1",
    description="Cursos de Engenharia, Ciência da Computação e Administração.",
)
classify_job(br_summer)
assert "summer_internship" in br_summer.detected_intents
assert "internship" in br_summer.detected_intents

vacation = Job(
    source="test",
    source_job_id="2",
    company="Empresa",
    title="Programa de Estágio de Férias - Janeiro 2027",
    location="São Paulo - SP",
    url="https://example.com/2",
)
classify_job(vacation)
assert "summer_internship" in vacation.detected_intents
assert "internship" in vacation.detected_intents

summer_job = Job(
    source="test",
    source_job_id="3",
    company="Resort",
    title="Summer Job - Atendimento Temporário",
    location="Florianópolis - SC",
    url="https://example.com/3",
)
classify_job(summer_job)
assert "seasonal_job" in summer_job.detected_intents

queries = build_collection_queries(60)
assert "estagio" in queries
assert any("estagio de verao" in q for q in queries)
assert any("estagio de ferias" in q for q in queries)
assert any("jovem aprendiz" in q for q in queries)
assert any("trainee" in q for q in queries)
assert any("engenharia eletr" in q or "engenharia elétrica" in q for q in queries)

print("BR summer intents:", br_summer.detected_intents)
print("Vacation intents:", vacation.detected_intents)
print("Summer job intents:", summer_job.detected_intents)
print("Collection queries:", len(queries))
print("Sample:", queries[:20])
print("OK: v3.5 collect-first/filter-later regression tests")
