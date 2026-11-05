package br.ufscar.opportunityradar;

import br.ufscar.opportunityradar.config.VisitorIdentityFilter;
import br.ufscar.opportunityradar.repository.ApplicationRepository;
import br.ufscar.opportunityradar.repository.FavoriteRepository;
import br.ufscar.opportunityradar.repository.UserAccountRepository;
import br.ufscar.opportunityradar.service.AccountService;
import br.ufscar.opportunityradar.domain.Favorite;
import br.ufscar.opportunityradar.domain.ApplicationEntry;
import br.ufscar.opportunityradar.domain.ApplicationStatus;
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
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.security.test.web.servlet.response.SecurityMockMvcResultMatchers.authenticated;
import static org.springframework.security.test.web.servlet.response.SecurityMockMvcResultMatchers.unauthenticated;

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
    @Autowired UserAccountRepository users;
    @Autowired AccountService accounts;

    @BeforeEach void resetUserData() {
        applications.deleteAll();
        favorites.deleteAll();
        users.deleteAll();
        accounts.register("alice", "sampleStrongPassword12", "sampleStrongPassword12");
        accounts.register("bob", "anotherStrongPassword12", "anotherStrongPassword12");
    }


    @Test
    void rendersCatalogAndAdvancedFiltersWithoutLogin() throws Exception {
        mvc.perform(get("/opportunities"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Vaga encerrada"))));
        mvc.perform(get("/opportunities").param("activeOnly", "false"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Vaga encerrada")));
        mvc.perform(get("/opportunities").param("course", "electrical_engineering")
            .param("minScore", "85")).andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(get("/opportunities").param("intent", "internship"))
            .andExpect(status().isOk());
        mvc.perform(get("/opportunities").param("source", "invalid"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Nenhuma oportunidade encontrada")));
    }

    @Test
    void findsNearbyOpportunitiesAndSortsByAffinity() throws Exception {
        mvc.perform(get("/opportunities").param("activeOnly","false")
            .param("latitude","-22.01").param("longitude","-47.89")
            .param("radiusKm","50").param("sort","distance"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("0.0 km")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Vaga encerrada"))));
        mvc.perform(get("/opportunities").param("activeOnly","false")
            .param("sort","relevance").param("minScore","80"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("90% afinidade")));
        mvc.perform(get("/opportunities").param("include","Java").param("exclude","Beta"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
    }

    @Test
    void allowsPublicDetailsButShowsLoginInsteadOfPrivateForms() throws Exception {
        mvc.perform(get("/opportunities/" + ID))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Aprenda Java e SQL")))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Entre para salvar favoritos")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("name=\"_csrf\""))));
        mvc.perform(get("/opportunities/" + ID).with(user("alice")))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("name=\"_csrf\"")))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Salvar acompanhamento")));
        mvc.perform(get("/opportunities/" + CLOSED))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("javascript:alert(1)"))));
        mvc.perform(get("/opportunities/nao-existe")).andExpect(status().isNotFound());
    }

    @Test
    void protectsFavoritesApplicationsAndProfileWithoutLogin() throws Exception {
        mvc.perform(get("/favorites"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrlPattern("**/login"));
        mvc.perform(get("/applications"))
            .andExpect(status().is3xxRedirection());
        mvc.perform(get("/profile")).andExpect(status().is3xxRedirection());
        mvc.perform(post("/favorites/" + ID).with(csrf()))
            .andExpect(status().is3xxRedirection());
    }

    @Test
    void servesLoginAndRegistrationFormsWithCsrf() throws Exception {
        mvc.perform(get("/login")).andExpect(status().isOk())
            .andExpect(view().name("auth/login"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("name=\"_csrf\"")));
        mvc.perform(get("/register")).andExpect(status().isOk())
            .andExpect(view().name("auth/register"))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("name=\"_csrf\"")));
    }

    @Test
    void registersUsersWithBCryptAndRejectsDuplicateOrInvalidPasswords() throws Exception {
        mvc.perform(post("/register").with(csrf()).param("username","Carol")
            .param("password","strongSamplePassword15")
            .param("confirmPassword","strongSamplePassword15"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("/login"));
        var carol = users.findByUsername("carol").orElseThrow();
        assertThat(carol.getPasswordHash()).startsWith("$2");
        assertThat(carol.getPasswordHash()).doesNotContain("strongSamplePassword15");
        mvc.perform(post("/register").with(csrf()).param("username","Carol")
            .param("password","strongSamplePassword15")
            .param("confirmPassword","strongSamplePassword15"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("já está em uso")));
        mvc.perform(post("/register").with(csrf()).param("username","invalid name")
            .param("password","strongSamplePassword15")
            .param("confirmPassword","strongSamplePassword15"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("letras sem acento")));
        mvc.perform(post("/register").with(csrf()).param("username","dan")
            .param("password","short").param("confirmPassword","short"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("10 a 64")));
        mvc.perform(post("/register").with(csrf()).param("username","dan")
            .param("password","strongSamplePassword15").param("confirmPassword","different"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("não corresponde")));
    }

    @Test
    void logsInWithPasswordAndRejectsWrongCredentials() throws Exception {
        mvc.perform(post("/login").with(csrf()).param("username","alice")
            .param("password","wrong")).andExpect(unauthenticated())
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("/login?error"));
        mvc.perform(post("/login").with(csrf()).param("username","alice")
            .param("password","sampleStrongPassword12")).andExpect(authenticated())
            .andExpect(status().is3xxRedirection());
        mvc.perform(post("/login").param("username","alice")
            .param("password","sampleStrongPassword12")).andExpect(status().isForbidden());
    }

    @Test
    void favoritesAreSynchronizedAcrossBrowsersOfSameUserButIsolatedFromOthers() throws Exception {
        String aliceId = users.findByUsername("alice").orElseThrow().getId();
        String bobId = users.findByUsername("bob").orElseThrow().getId();
        mvc.perform(post("/favorites/" + ID).cookie(browser(DEVICE_A)).with(user("alice")).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(aliceId, ID)).isPresent();
        assertThat(favorites.findByOwnerIdAndOpportunityId(bobId, ID)).isEmpty();
        mvc.perform(get("/favorites").cookie(browser(DEVICE_B)).with(user("alice")))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(get("/favorites").cookie(browser(DEVICE_B)).with(user("bob")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Estágio em engenharia"))));
        mvc.perform(post("/favorites/" + ID).with(user("bob")).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOwnerIdAndOpportunityId(bobId, ID)).isPresent();
        assertThat(favorites.findByOwnerIdAndOpportunityId(aliceId, ID)).isPresent();
        mvc.perform(post("/favorites/" + ID).with(user("alice")).with(csrf()));
        assertThat(favorites.findByOwnerIdAndOpportunityId(aliceId, ID)).isEmpty();
        assertThat(favorites.findByOwnerIdAndOpportunityId(bobId, ID)).isPresent();
    }

    @Test
    void applicationTrackingIsPerAccountAndSupportsFullCrud() throws Exception {
        String aliceId = users.findByUsername("alice").orElseThrow().getId();
        String bobId = users.findByUsername("bob").orElseThrow().getId();
        mvc.perform(post("/applications/" + ID).with(user("alice")).with(csrf())
            .param("status","PLANNED").param("notes","Enviar CV"))
            .andExpect(status().is3xxRedirection());
        mvc.perform(post("/applications/" + ID).with(user("alice")).with(csrf())
            .param("status","INTERVIEW").param("notes","Entrevista no celular"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(aliceId, ID)
            .orElseThrow().getStatus()).isEqualTo(ApplicationStatus.INTERVIEW);
        assertThat(applications.findByOwnerIdAndOpportunityId(bobId, ID)).isEmpty();
        mvc.perform(get("/applications").with(user("alice")))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Entrevista no celular")));
        mvc.perform(get("/applications").with(user("bob")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Entrevista no celular"))));
        mvc.perform(post("/applications/" + ID + "/delete").with(user("alice")).with(csrf()))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOwnerIdAndOpportunityId(aliceId, ID)).isEmpty();
    }

    @Test
    void automaticallyImportsExistingAnonymousFavoritesAndApplicationsOnLogin() throws Exception {
        favorites.save(new Favorite(DEVICE_A, ID));
        applications.save(new ApplicationEntry(DEVICE_A, ID, ApplicationStatus.APPLIED, "Nota antiga"));
        mvc.perform(post("/login").cookie(browser(DEVICE_A)).with(csrf())
            .param("username","alice").param("password","sampleStrongPassword12"))
            .andExpect(authenticated())
            .andExpect(status().is3xxRedirection());
        String aliceId = users.findByUsername("alice").orElseThrow().getId();
        assertThat(favorites.findByOwnerIdAndOpportunityId(aliceId, ID)).isPresent();
        assertThat(applications.findByOwnerIdAndOpportunityId(aliceId, ID)
            .orElseThrow().getNotes()).isEqualTo("Nota antiga");
        assertThat(favorites.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
        assertThat(applications.findByOwnerIdAndOpportunityId(DEVICE_A, ID)).isEmpty();
    }

    @Test
    void rejectsCrossSiteWritesAndInvalidTrackingValues() throws Exception {
        mvc.perform(post("/favorites/" + ID).with(user("alice")))
            .andExpect(status().isForbidden());
        mvc.perform(post("/applications/" + ID).with(user("alice")).with(csrf())
            .param("status","INVALID")).andExpect(status().isBadRequest());
        mvc.perform(post("/applications/" + ID).with(user("alice")).with(csrf())
            .param("status","PLANNED").param("notes","x".repeat(2001)))
            .andExpect(status().isBadRequest());
        assertThat(applications.findAll()).isEmpty();
    }

    @Test
    void profileShowsUsernameInsteadOfRecoveryCodeAndLogoutRequiresPost() throws Exception {
        mvc.perform(get("/profile").with(user("alice")))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("alice")))
            .andExpect(content().string(org.hamcrest.Matchers.not(
                org.hamcrest.Matchers.containsString("Código de recuperação"))))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("name=\"_csrf\"")));
        mvc.perform(post("/logout").with(user("alice")).with(csrf()))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("/login?logout"));
    }

    @Test
    void sqliteIndexesExistAndActivePostingLookupUsesCoveringIndex() {
        var indexes = jdbc.queryForList(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_web_%'", String.class);
        assertThat(indexes).contains("idx_web_postings_opp_active_source",
            "idx_web_opportunities_updated", "idx_web_course_scores_course_score");
        var plan = jdbc.queryForList("""
            EXPLAIN QUERY PLAN SELECT o.id FROM opportunities o WHERE EXISTS
            (SELECT 1 FROM source_postings p WHERE p.opportunity_id=o.id AND p.is_active=1)
            ORDER BY o.updated_at DESC LIMIT 12
            """).stream().map(row -> String.valueOf(row.get("detail"))).toList();
        assertThat(plan).anyMatch(item -> item.contains("idx_web_postings_opp_active_source"));
    }
}
