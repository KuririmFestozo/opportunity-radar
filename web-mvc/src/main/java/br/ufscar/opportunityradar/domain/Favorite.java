package br.ufscar.opportunityradar.domain;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(name = "web_device_favorites",
    uniqueConstraints = @UniqueConstraint(columnNames = {"owner_id", "opportunity_id"}))
public class Favorite {
    @Id private String id;
    @Column(name = "owner_id", nullable = false, length = 64)
    private String ownerId;
    @Column(name = "opportunity_id", nullable = false)
    private String opportunityId;
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    protected Favorite() {}
    public Favorite(String ownerId, String opportunityId) {
        this.id = UUID.randomUUID().toString();
        this.ownerId = ownerId;
        this.opportunityId = opportunityId;
        this.createdAt = Instant.now().toString();
    }
    public String getId() { return id; }
    public String getOwnerId() { return ownerId; }
    public String getOpportunityId() { return opportunityId; }
    public String getCreatedAt() { return createdAt; }
}
