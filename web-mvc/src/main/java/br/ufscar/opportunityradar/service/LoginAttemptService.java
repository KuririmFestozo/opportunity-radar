package br.ufscar.opportunityradar.service;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.security.authentication.LockedException;
import org.springframework.stereotype.Service;

/** Short local throttle for the temporary tunnel: eight bad attempts per username per 15 min. */
@Service
public class LoginAttemptService {
    private record Failure(int count, long expiresAtMs) {}
    private final ConcurrentHashMap<String, Failure> attempts = new ConcurrentHashMap<>();
    private static final int MAX_FAILURES = 8;
    private static final long WINDOW_MS = 15 * 60 * 1000L;

    public boolean blocked(String rawUsername) {
        String name = AccountService.normalize(rawUsername);
        Failure found = attempts.get(name);
        if (found == null) return false;
        if (System.currentTimeMillis() >= found.expiresAtMs()) {
            attempts.remove(name, found);
            return false;
        }
        return found.count() >= MAX_FAILURES;
    }

    public void onFailure(String rawUsername) {
        String name = AccountService.normalize(rawUsername);
        // Bound the in-memory map if an attacker submits many unique usernames.
        if (attempts.size() > 10000) attempts.clear();
        long now = System.currentTimeMillis();
        attempts.compute(name, (key, old) -> old == null || now >= old.expiresAtMs()
            ? new Failure(1, now + WINDOW_MS)
            : new Failure(Math.min(MAX_FAILURES, old.count() + 1), old.expiresAtMs()));
    }
    public void onSuccess(String rawUsername) {
        attempts.remove(AccountService.normalize(rawUsername));
    }
}
