package br.ufscar.opportunityradar.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.HexFormat;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Anonymous, persistent browser identity. A visitor has their own favorites
 * and applications; no third-party login and no device fingerprinting.
 * The cookie is a bearer credential: keep it HttpOnly and unguessable.
 */
@Component
public class VisitorIdentityFilter extends OncePerRequestFilter {
    public static final String ATTRIBUTE = "radarVisitorId";
    public static final String COOKIE = "radar_visitor";
    private static final SecureRandom RANDOM = new SecureRandom();

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String visitorId = null;
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if (COOKIE.equals(cookie.getName()) && cookie.getValue().matches("[a-f0-9]{64}")) {
                    visitorId = cookie.getValue();
                    break;
                }
            }
        }
        if (visitorId == null) {
            byte[] entropy = new byte[32];
            RANDOM.nextBytes(entropy);
            visitorId = HexFormat.of().formatHex(entropy);
            response.addHeader(HttpHeaders.SET_COOKIE, ResponseCookie.from(COOKIE, visitorId)
                .httpOnly(true)
                .secure(request.isSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofDays(365))
                .build().toString());
        }
        request.setAttribute(ATTRIBUTE, visitorId);
        chain.doFilter(request, response);
    }
}
