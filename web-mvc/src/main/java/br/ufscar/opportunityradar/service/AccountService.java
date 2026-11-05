package br.ufscar.opportunityradar.service;

import br.ufscar.opportunityradar.domain.UserAccount;
import br.ufscar.opportunityradar.repository.UserAccountRepository;
import java.nio.charset.StandardCharsets;
import java.security.Principal;
import java.util.Locale;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AccountService implements UserDetailsService {
    private final UserAccountRepository users;
    private final PasswordEncoder passwordEncoder;
    private final LoginAttemptService attempts;

    public AccountService(UserAccountRepository users, PasswordEncoder passwordEncoder,
                          LoginAttemptService attempts) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
        this.attempts = attempts;
    }

    @Transactional
    public void register(String rawUsername, String password, String confirmation) {
        String username = normalize(rawUsername);
        if (!username.matches("[a-z0-9][a-z0-9._-]{2,39}")) {
            throw new IllegalArgumentException(
                "Use um usuário de 3 a 40 caracteres: letras sem acento, números, ponto, hífen ou _.");
        }
        if (password == null || password.length() < 10 || password.length() > 64
            || password.getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new IllegalArgumentException("Use uma senha de 10 a 64 caracteres.");
        }
        if (!password.equals(confirmation)) {
            throw new IllegalArgumentException("A confirmação da senha não corresponde.");
        }
        if (users.existsByUsername(username)) {
            throw new IllegalArgumentException("Este nome de usuário já está em uso.");
        }
        try {
            users.saveAndFlush(new UserAccount(username, passwordEncoder.encode(password)));
        } catch (DataIntegrityViolationException duplicate) {
            throw new IllegalArgumentException("Este nome de usuário já está em uso.");
        }
    }

    public String ownerId(Principal principal) {
        if (principal == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Entre na sua conta.");
        }
        return users.findByUsername(normalize(principal.getName()))
            .map(UserAccount::getId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED));
    }

    @Override
    public UserDetails loadUserByUsername(String rawUsername) throws UsernameNotFoundException {
        if (attempts.blocked(rawUsername)) {
            throw new UsernameNotFoundException("Usuário ou senha incorretos ou temporariamente bloqueados.");
        }
        return users.findByUsername(normalize(rawUsername))
            .map(u -> User.withUsername(u.getUsername())
                .password(u.getPasswordHash())
                .roles("USER")
                .build())
            .orElseThrow(() -> new UsernameNotFoundException("Usuário ou senha incorretos."));
    }

    public static String normalize(String value) {
        return value == null ? "" : value.strip().toLowerCase(Locale.ROOT);
    }
}
