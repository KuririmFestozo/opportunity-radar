-- Six clearly fictional opportunities for a reproducible classroom demo.
-- No passwords or accounts are seeded: users register in the web application.
INSERT INTO opportunities
  (id, company, title, description, location_text, workplace_type, employment_type,
   published_at, canonical_url, updated_at, latitude, longitude)
VALUES
 ('11111111-1111-4111-8111-111111111111','Aurora Energia (exemplo)',
  'Estágio em Engenharia Elétrica','Oportunidade fictícia para demonstração.',
  'São Carlos, SP','hybrid','internship','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/1','2026-11-05T12:00:00Z',-22.01,-47.89),
 ('22222222-2222-4222-8222-222222222222','Horizonte Tech (exemplo)',
  'Desenvolvedor Júnior','Oportunidade fictícia para demonstração.',
  'Campinas, SP','remote','entry_level','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/2','2026-11-05T12:00:00Z',-22.91,-47.06),
 ('33333333-3333-4333-8333-333333333333','Verde Futuro (exemplo)',
  'Pesquisa em Sustentabilidade','Oportunidade fictícia para demonstração.',
  'São Paulo, SP','onsite','research','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/3','2026-11-05T12:00:00Z',-23.55,-46.63),
 ('44444444-4444-4444-8444-444444444444','Atlas Sistemas (exemplo)',
  'Estágio em Software','Oportunidade fictícia para demonstração.',
  'Ribeirão Preto, SP','hybrid','internship','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/4','2026-11-05T12:00:00Z',-21.18,-47.81),
 ('55555555-5555-4555-8555-555555555555','Oficina Solar (exemplo)',
  'Programa de Trainee','Oportunidade fictícia para demonstração.',
  'Sorocaba, SP','onsite','trainee','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/5','2026-11-05T12:00:00Z',-23.50,-47.46),
 ('66666666-6666-4666-8666-666666666666','Laboratório Terra (exemplo)',
  'Estágio em Análise de Dados','Oportunidade fictícia para demonstração.',
  'Araraquara, SP','remote','internship','2026-11-01T12:00:00Z',
  'https://example.org/oportunidade/6','2026-11-05T12:00:00Z',-21.79,-48.18)
ON CONFLICT (id) DO NOTHING;

INSERT INTO source_postings
  (source, source_job_id, opportunity_id, is_active, url, last_seen_at)
SELECT 'demo', CAST(n AS TEXT), CAST(oid AS TEXT), TRUE,
       'https://example.org/oportunidade/' || CAST(n AS TEXT), '2026-11-05T12:00:00Z'
FROM (VALUES
  (1,'11111111-1111-4111-8111-111111111111'),
  (2,'22222222-2222-4222-8222-222222222222'),
  (3,'33333333-3333-4333-8333-333333333333'),
  (4,'44444444-4444-4444-8444-444444444444'),
  (5,'55555555-5555-4555-8555-555555555555'),
  (6,'66666666-6666-4666-8666-666666666666')
) AS ids(n,oid)
ON CONFLICT (source,source_job_id) DO NOTHING;

INSERT INTO opportunity_course_scores(opportunity_id,course_id,score) VALUES
 ('11111111-1111-4111-8111-111111111111','engenharia_eletrica',92),
 ('22222222-2222-4222-8222-222222222222','ciencia_computacao',77),
 ('33333333-3333-4333-8333-333333333333','engenharia_ambiental',85),
 ('44444444-4444-4444-8444-444444444444','ciencia_computacao',91),
 ('55555555-5555-4555-8555-555555555555','engenharia_mecanica',68),
 ('66666666-6666-4666-8666-666666666666','ciencia_dados',82)
ON CONFLICT (opportunity_id,course_id) DO NOTHING;

INSERT INTO opportunity_intents(opportunity_id,intent_id) VALUES
 ('11111111-1111-4111-8111-111111111111','internship'),
 ('22222222-2222-4222-8222-222222222222','entry_level'),
 ('33333333-3333-4333-8333-333333333333','research'),
 ('44444444-4444-4444-8444-444444444444','internship'),
 ('55555555-5555-4555-8555-555555555555','trainee'),
 ('66666666-6666-4666-8666-666666666666','internship')
ON CONFLICT (opportunity_id,intent_id) DO NOTHING;
