package br.ufscar.opportunityradar.config;

import br.ufscar.opportunityradar.service.AccountMigrationService;
import br.ufscar.opportunityradar.service.LoginAttemptService;
import jakarta.servlet.http.Cookie;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.SavedRequestAwareAuthenticationSuccessHandler;
import org.springframework.security.web.authentication.AuthenticationFailureHandler;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import br.ufscar.opportunityradar.service.AccountService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Configuration
public class WebSecurityConfig {
    private static final Logger LOG = LoggerFactory.getLogger(WebSecurityConfig.class);

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    @Bean
    AuthenticationProvider authenticationProvider(AccountService accounts,
                                                  PasswordEncoder encoder,
                                                  LoginAttemptService attempts) {
        DaoAuthenticationProvider provider = new DaoAuthenticationProvider();
        provider.setUserDetailsService(accounts);
        provider.setPasswordEncoder(encoder);
        return provider;
    }

    @Bean
    SecurityFilterChain webSecurity(HttpSecurity http, AuthenticationProvider provider,
                                    AccountMigrationService migration,
                                    LoginAttemptService attempts) throws Exception {
        AuthenticationSuccessHandler success = (request, response, auth) -> {
            attempts.onSuccess(auth.getName());
            String visitor = null;
            if (request.getCookies() != null) {
                for (Cookie cookie : request.getCookies()) {
                    if (VisitorIdentityFilter.COOKIE.equals(cookie.getName())) {
                        visitor = cookie.getValue();
                        break;
                    }
                }
            }
            try {
                migration.importBrowserData(auth, visitor);
            } catch (RuntimeException error) {
                // Authentication succeeds; old anonymous data remains intact on rollback.
                LOG.warn("Could not migrate anonymous collections on login", error);
                request.getSession().setAttribute("radarMigrationWarning", Boolean.TRUE);
            }
            SavedRequestAwareAuthenticationSuccessHandler handler = new SavedRequestAwareAuthenticationSuccessHandler();
            handler.setDefaultTargetUrl("/favorites");
            handler.onAuthenticationSuccess(request, response, auth);
        };
        AuthenticationFailureHandler failure = (request, response, exception) -> {
            attempts.onFailure(request.getParameter("username"));
            response.sendRedirect(request.getContextPath() + "/login?error");
        };

        http.authenticationProvider(provider)
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/", "/opportunities", "/opportunities/**",
                    "/login", "/register", "/css/**", "/js/**", "/favicon.ico").permitAll()
                .anyRequest().authenticated())
            .formLogin(login -> login.loginPage("/login").loginProcessingUrl("/login")
                .successHandler(success).failureHandler(failure).permitAll())
            .logout(logout -> logout.logoutUrl("/logout")
                .logoutSuccessUrl("/login?logout")
                .invalidateHttpSession(true).deleteCookies("JSESSIONID"))
            .sessionManagement(session -> session.sessionFixation(fix -> fix.migrateSession()));
        return http.build();
    }
}
