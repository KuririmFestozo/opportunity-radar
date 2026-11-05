package br.ufscar.opportunityradar.domain;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(name = "web_device_applications",
    uniqueConstraints = @UniqueConstraint(columnNames = {"owner_id", "opportunity_id"}))
public class ApplicationEntry {
    @Id private String id;
    @Column(name = "owner_id", nullable = false, length = 64)
    private String ownerId;
    @Column(name = "opportunity_id", nullable = false)
    private String opportunityId;
    @Enumerated(EnumType.STRING)
    private ApplicationStatus status;
    @Column(columnDefinition = "TEXT", nullable = false)
    private String notes;
    @Column(name = "updated_at", nullable = false)
    private String updatedAt;

    protected ApplicationEntry() {}
    public ApplicationEntry(String ownerId, String opportunityId, ApplicationStatus status, String notes) {
        this.id = UUID.randomUUID().toString();
        this.ownerId = ownerId;
        this.opportunityId = opportunityId;
        update(status, notes);
    }
    public void update(ApplicationStatus newStatus, String newNotes) {
        status = newStatus;
        notes = newNotes;
        updatedAt = Instant.now().toString();
    }
    public String getId() { return id; }
    public String getOwnerId() { return ownerId; }
    public String getOpportunityId() { return opportunityId; }
    public ApplicationStatus getStatus() { return status; }
    public String getNotes() { return notes; }
    public String getUpdatedAt() { return updatedAt; }
}
