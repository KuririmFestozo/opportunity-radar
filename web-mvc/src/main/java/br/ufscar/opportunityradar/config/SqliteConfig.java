package br.ufscar.opportunityradar.config;

import java.nio.file.Files;
import java.nio.file.Path;
import javax.sql.DataSource;

import org.sqlite.SQLiteConfig;
import org.sqlite.SQLiteDataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
public class SqliteConfig {
    @Bean
    public DataSource dataSource(@Value("${radar.db.path}") String configuredPath) {
        Path path = Path.of(configuredPath).toAbsolutePath().normalize();
        if (!Files.isRegularFile(path)) {
            throw new IllegalStateException(
                "SQLite nao encontrado: " + path + ". Defina RADAR_DB_PATH para um snapshot valido.");
        }
        SQLiteConfig options = new SQLiteConfig();
        options.enforceForeignKeys(true);
        options.setBusyTimeout(8000);
        SQLiteDataSource dataSource = new SQLiteDataSource(options);
        dataSource.setUrl("jdbc:sqlite:" + path);
        return dataSource;
    }

    @Bean
    public ApplicationRunner checkExistingRadarSchema(JdbcTemplate jdbc) {
        return args -> {
            for (String table : new String[]{"opportunities", "source_postings", "opportunity_course_scores"}) {
                Integer count = jdbc.queryForObject(
                    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", Integer.class, table);
                if (count == null || count != 1) {
                    throw new IllegalStateException(
                        "O SQLite nao possui a tabela " + table
                        + ". Use um snapshot do Opportunity Radar CP4; nao um banco vazio.");
                }
            }
        };
    }
}
