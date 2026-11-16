package br.ufscar.opportunityradar.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * View-only fallback for GET /login.
 *
 * The annotated AuthController handler, when present, takes precedence.
 * This mapping does not process credentials: Spring Security still owns
 * POST /login and all authorization rules.
 */
@Configuration
public class LoginViewFallbackConfig implements WebMvcConfigurer {

    @Override
    public void addViewControllers(ViewControllerRegistry registry) {
        registry.addViewController("/login").setViewName("auth/login");
    }
}
