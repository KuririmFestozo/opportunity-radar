package br.ufscar.opportunityradar.config;

import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
public class PostgresCatalogCheck {
    @Bean
    public ApplicationRunner verifyCatalogSchema(JdbcTemplate jdbc) {
        return args -> {
            for (String table : new String[]{
                    "opportunities", "source_postings", "opportunity_course_scores", "web_users"}) {
                Integer count = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = current_schema() AND table_name = ?
                    """, Integer.class, table);
                if (count == null || count != 1) {
                    throw new IllegalStateException(
                        "Tabela PostgreSQL ausente: " + table + ". Confira os scripts em db/.");
                }
            }
        };
    }
}
