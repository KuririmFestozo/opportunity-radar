package br.ufscar.opportunityradar.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "web_users")
public class UserAccount {
    @Id private String id;
    @Column(nullable = false, unique = true, length = 40)
    private String username;
    @Column(name = "password_hash", nullable = false)
    private String passwordHash;
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    protected UserAccount() {}
    public UserAccount(String username, String passwordHash) {
        this.id = UUID.randomUUID().toString();
        this.username = username;
        this.passwordHash = passwordHash;
        this.createdAt = Instant.now().toString();
    }
    public String getId() { return id; }
    public String getUsername() { return username; }
    public String getPasswordHash() { return passwordHash; }
    public String getCreatedAt() { return createdAt; }
}
