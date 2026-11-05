package br.ufscar.opportunityradar;

import br.ufscar.opportunityradar.repository.ApplicationRepository;
import br.ufscar.opportunityradar.repository.FavoriteRepository;
import br.ufscar.opportunityradar.service.CatalogService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
class OpportunityRadarWebIntegrationTest {
    private static final String ID = "11111111-1111-4111-8111-111111111111";
    private static final String CLOSED = "22222222-2222-4222-8222-222222222222";
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
                      canonical_url TEXT, updated_at TEXT NOT NULL
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
                stmt.executeUpdate("""
                    INSERT INTO opportunities VALUES
                    ('11111111-1111-4111-8111-111111111111','Acme','Estágio em engenharia',
                     'Aprenda Java e SQL','São Carlos, SP','hybrid','internship',
                     '2026-11-01','https://example.com/job/1','2026-11-05'),
                    ('22222222-2222-4222-8222-222222222222','Beta','Vaga encerrada',
                     'Vaga antiga','Campinas, SP','remote','trainee',
                     '2026-10-01','javascript:alert(1)','2026-10-05')
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
            }
            db.toFile().deleteOnExit();
            return db;
        } catch (Exception ex) {
            throw new IllegalStateException("Nao foi possivel preparar SQLite de teste", ex);
        }
    }

    @Autowired MockMvc mvc;
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
        mvc.perform(post("/favorites/" + ID))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOpportunityId(ID)).isPresent();
        mvc.perform(get("/favorites"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Estágio em engenharia")));
        mvc.perform(post("/favorites/" + ID))
            .andExpect(status().is3xxRedirection());
        assertThat(favorites.findByOpportunityId(ID)).isEmpty();
    }

    @Test
    void applicationsSupportCreateUpdateAndDelete() throws Exception {
        mvc.perform(post("/applications/" + ID).param("status","PLANNED").param("notes","Enviar CV"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOpportunityId(ID)).isPresent();
        mvc.perform(post("/applications/" + ID).param("status","INTERVIEW").param("notes","Entrevista dia 10"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOpportunityId(ID).orElseThrow().getStatus().name()).isEqualTo("INTERVIEW");
        assertThat(applications.findAll()).hasSize(1);
        mvc.perform(get("/applications"))
            .andExpect(status().isOk())
            .andExpect(content().string(org.hamcrest.Matchers.containsString("Entrevista")));
        mvc.perform(post("/applications/" + ID + "/delete"))
            .andExpect(status().is3xxRedirection());
        assertThat(applications.findByOpportunityId(ID)).isEmpty();
    }

    @Test
    void rejectsInvalidStatusOrOversizedNotes() throws Exception {
        mvc.perform(post("/applications/" + ID).param("status","HACK"))
            .andExpect(status().isBadRequest());
        mvc.perform(post("/applications/" + ID).param("status","PLANNED")
            .param("notes","x".repeat(2001)))
            .andExpect(status().isBadRequest());
        assertThat(applications.findAll()).isEmpty();
    }
}
