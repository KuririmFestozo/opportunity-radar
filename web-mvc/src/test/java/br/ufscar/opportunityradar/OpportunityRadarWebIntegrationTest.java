package br.ufscar.opportunityradar;

import br.ufscar.opportunityradar.config.VisitorIdentityFilter;
import br.ufscar.opportunityradar.repository.ApplicationRepository;
import br.ufscar.opportunityradar.repository.FavoriteRepository;
import br.ufscar.opportunityradar.service.CatalogService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import jakarta.servlet.http.Cookie;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
class OpportunityRadarWebIntegrationTest {
    private static final String ID = "11111111-1111-4111-8111-111111111111";
    private static final String CLOSED = "22222222-2222-4222-8222-222222222222";
    private static final String DEVICE_A = "a".repeat(64);
    private static final String DEVICE_B = "b".repeat(64);
    private static Cookie browser(String token) { return new Cookie(VisitorIdentityFilter.COOKIE, token); }
    private static final Path SQLITE = createFixture();

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("radar.db.path", SQLITE::toString);
    }

    private static Path createFixture() {
        try {
            Path db = Files.createTempFile("radar-mvc-test-", ".db");
            try (var conn = DriverManager.getConnection("jdbc:sqlite:" + db);
                 var stmt = conn.createStatement()) {
                stmt.executeUpdate("""
                    CREATE TABLE opportunities (
                      id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
                      description TEXT NOT NULL, location_text TEXT NOT NULL,
                      workplace_type TEXT, employment_type TEXT, published_at TEXT,
                      canonical_url TEXT, updated_at TEXT NOT NULL,
                      latitude REAL, longitude REAL
                    )""");
                stmt.executeUpdate("""
                    CREATE TABLE source_postings (
                      source TEXT NOT NULL, source_job_id TEXT NOT NULL,
                      opportunity_id TEXT NOT NULL, is_active INTEGER NOT NULL,
                      url TEXT, last_seen_at TEXT,
                      PRIMARY KEY (source, source_job_id)
                    )""");
                stmt.executeUpdate("""
                    CREATE TABLE opportunity_course_scores (
                      opportunity_id TEXT NOT NULL, course_id TEXT NOT NULL, score INTEGER NOT NULL,
                      PRIMARY KEY(opportunity_id, course_id)
                    )""");
                stmt.executeUpdate("CREATE TABLE opportunity_intents (opportunity_id TEXT NOT NULL, intent_id TEXT NOT NULL, PRIMARY KEY(opportunity_id,intent_id))");
                stmt.executeUpdate("""
                    INSERT INTO opportunities VALUES
                    ('11111111-1111-4111-8111-111111111111','Acme','Estágio em engenharia',
                     'Aprenda Java e SQL','São Carlos, SP','hybrid','internship',
                     '2026-11-01','https://example.com/job/1','2026-11-05',-22.01,-47.89),
                    ('22222222-2222-4222-8222-222222222222','Beta','Vaga encerrada',
                     'Vaga antiga','Campinas, SP','remote','trainee',
                     '2026-10-01','javascript:alert(1)','2026-10-05',-22.91,-47.06)
                    """);
                stmt.executeUpdate("""
                    INSERT INTO source_postings VALUES
                    ('workday','A1','11111111-1111-4111-8111-111111111111',1,
                     'https://example.com/job/1','2026-11-05'),
                    ('gupy_global','B1','22222222-2222-4222-8222-222222222222',0,
                     'https://example.com/job/2','2026-10-05')
                    """);
                stmt.executeUpdate("""
                    INSERT INTO opportunity_course_scores VALUES
                    ('11111111-1111-4111-8111-111111111111','electrical_engineering',90),
                    ('22222222-2222-4222-8222-222222222222','computer_science',10)
                    """);
                stmt.executeUpdate("INSERT INTO opportunity_intents VALUES ('11111111-1111-4111-8111-111111111111','internship')");
            }
            db.toFile().deleteOnExit();
            return db;
        } catch (Exception ex) {
            throw new IllegalStateException("Nao foi possivel preparar SQLite de teste", ex);
        }
    }

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired FavoriteRepository favorites;
    @Autowired ApplicationRepository applications;

    @BeforeEach void resetUserData() {
        applications.deleteAll();
        favorites.deleteAll();
    }

    @Test
    void rendersSearchAndFiltersByActiveAndCourse() throws Exception {
        mvc.perform(get("/opportunities"))
            .andExpect(status().isOk())
            .andExpect(view().name("opportunities"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Vaga encerrada"))));
        mvc.perform(get("/opportunities").param("activeOnly","false"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Vaga encerrada")));
        mvc.perform(get("/opportunities")
            .param("course","electrical_engineering").param("minScore","85"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(get("/opportunities")
            .param("course","electrical_engineering").param("minScore","99"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Nenhuma oportunidade encontrada")));
        mvc.perform(get("/opportunities").param("source","invalid"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Nenhuma oportunidade encontrada")));
    }

    @Test
    void opensDetailsAndRejectsUnsafeExternalLink() throws Exception {
        mvc.perform(get("/opportunities/" + ID))
            .andExpect(status().isOk())
            .andExpect(view().name("detail"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Aprenda Java e SQL")))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("90%")));
        mvc.perform(get("/opportunities/" + CLOSED))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("javascript:alert(1)"))));
        mvc.perform(get("/opportunities/nao-existe"))
            .andExpect(status().isNotFound());
        assertThat(CatalogService.safeUrl("javascript:alert(1)")).isNull();
        assertThat(CatalogService.safeUrl("https://example.com/vaga")).isEqualTo("https://example.com/vaga");
    }

    @Test
    void favoritesArePersistedAndCanBeRemoved() throws Exception {
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isPresent();
        mvc.perform(get("/favorites").cookie(browser(DEVICE_A)))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
    }

    @Test
    void applicationsSupportCreateUpdateAndDelete() throws Exception {
        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_A)).with(csrf()).param("status","PLANNED").param("notes","Enviar CV"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isPresent();
        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_A)).with(csrf()).param("status","INTERVIEW").param("notes","Entrevista dia 10"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_A, ID).orElseThrow().getStatus().name()).isEqualTo("INTERVIEW");
        assertThat(applications.findAll()).hasSize(1);
        mvc.perform(get("/applications").cookie(browser(DEVICE_A)))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Entrevista")));
        mvc.perform(post("/applications/" + ID + "/delete").cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
    }

    @Test
    void rejectsInvalidStatusOrOversizedNotes() throws Exception {
        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_A)).with(csrf()).param("status","HACK"))
            .andExpect(status().isBadRequest());
        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_A)).with(csrf()).param("status","PLANNED")
            .param("notes","x".repeat(2001)))
            .andExpect(status().isBadRequest());
        assertThat(applications.findAll()).isEmpty();
    }



    @Test
    void browserIdentitiesKeepFavoritesAndApplicationsSeparate() throws Exception {
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isPresent();
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_B, ID)).isEmpty();
        mvc.perform(get("/favorites").cookie(browser(DEVICE_B)))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Estágio em engenharia"))));
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_B)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_B, ID)).isPresent();

        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_A)).with(csrf())
            .param("status","PLANNED").param("notes","Apenas no computador"))
            .andExpect(status().is3xxRedirection());
        mvc.perform(post("/applications/" + ID).cookie(browser(DEVICE_B)).with(csrf())
            .param("status","INTERVIEW").param("notes","Apenas no celular"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_A, ID)
            .orElseThrow().getNotes()).isEqualTo("Apenas no computador");
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_B, ID)
            .orElseThrow().getNotes()).isEqualTo("Apenas no celular");
    }

    @Test
    void refusesCrossSitePostsWithoutCsrf() throws Exception {
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)))
            .andExpect(status().isForbidden());
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
    }

    @Test
    void advancedSearchSupportsGeoRadiusAffinitySortAndKeywords() throws Exception {
        mvc.perform(get("/opportunities").param("activeOnly","false")
            .param("latitude","-22.01").param("longitude","-47.89")
            .param("radiusKm","50").param("sort","distance"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Vaga encerrada"))))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("0.0 km")));

        mvc.perform(get("/opportunities").param("activeOnly","false")
            .param("sort","relevance").param("minScore","80"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("90% afinidade")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Vaga encerrada"))));

        mvc.perform(get("/opportunities").param("intent","internship"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(get("/opportunities").param("workplace","remote").param("activeOnly","false"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Vaga encerrada")));
        mvc.perform(get("/opportunities").param("include","Java").param("exclude","Beta"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
    }

    @Test
    void anonymousBrowserReceivesHttpOnlyVisitorCookie() throws Exception {
        mvc.perform(get("/favorites"))
            .andExpect(status().isOk())
            .andExpect(header().string("Set-Cookie",
                org.hamcrest.Matchers.containsString("radar_visitor=")))
            .andExpect(header().string("Set-Cookie",
                org.hamcrest.Matchers.containsString("HttpOnly")));
    }


    @Test
    void recoveryCodeRestoresBrowserCollectionsAcrossTunnelHostnames() throws Exception {
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection());
        mvc.perform(get("/profile").cookie(browser(DEVICE_A)))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString(DEVICE_A)));
        mvc.perform(post("/profile/restore").cookie(browser(DEVICE_B)).with(csrf())
            .param("recoveryCode", DEVICE_A))
            .andExpect(status().is3xxRedirection())
            .andExpect(header().string("Set-Cookie",
                org.hamcrest.Matchers.containsString("radar_visitor=" + DEVICE_A)));
        mvc.perform(get("/favorites").cookie(browser(DEVICE_A)))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(post("/profile/new").cookie(browser(DEVICE_A)).with(csrf()))
            .andExpect(status().is3xxRedirection())
            .andExpect(header().string("Set-Cookie",
                org.hamcrest.Matchers.containsString("radar_visitor=")));
        mvc.perform(post("/profile/restore").cookie(browser(DEVICE_B)).with(csrf())
            .param("recoveryCode","short"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("/profile"));
    }

    @Test
    void sqliteUsesIndexForActivePostingLookupOnCatalog() {
        var indexes = jdbc.queryForList(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_web_%'",
            String.class);
        assertThat(indexes).contains(
            "idx_web_postings_opp_active_source",
            "idx_web_opportunities_updated",
            "idx_web_course_scores_course_score");

        // Regression guard: a standalone is_active index used here produces
        // a correlated full scan per opportunity on real 20k+ snapshots.
        var plan = jdbc.queryForList("""
            EXPLAIN QUERY PLAN
            SELECT o.id FROM opportunities o
            WHERE EXISTS (
                SELECT 1 FROM source_postings p
                WHERE p.opportunity_id = o.id AND p.is_active = 1
            )
            ORDER BY o.updated_at DESC LIMIT 12
            """).stream().map(row -> String.valueOf(row.get("detail"))).toList();
        assertThat(plan).anyMatch(
            item -> item.contains("idx_web_postings_opp_active_source"));
    }
}
