package br.ufscar.opportunityradar.domain;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "web_favorites")
public class Favorite {
    @Id private String id;
    @Column(name = "opportunity_id", nullable = false, unique = true)
    private String opportunityId;
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    protected Favorite() {}
    public Favorite(String opportunityId) {
        this.id = UUID.randomUUID().toString();
        this.opportunityId = opportunityId;
        this.createdAt = Instant.now().toString();
    }
    public String getId() { return id; }
    public String getOpportunityId() { return opportunityId; }
    public String getCreatedAt() { return createdAt; }
}
