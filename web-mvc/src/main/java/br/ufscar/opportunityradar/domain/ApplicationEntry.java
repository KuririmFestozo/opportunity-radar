package br.ufscar.opportunityradar.domain;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "web_applications")
public class ApplicationEntry {
    @Id private String id;
    @Column(name = "opportunity_id", unique = true, nullable = false)
    private String opportunityId;
    @Enumerated(EnumType.STRING)
    private ApplicationStatus status;
    @Column(columnDefinition = "TEXT", nullable = false)
    private String notes;
    @Column(name = "updated_at", nullable = false)
    private String updatedAt;

    protected ApplicationEntry() {}
    public ApplicationEntry(String opportunityId, ApplicationStatus status, String notes) {
        this.id = UUID.randomUUID().toString();
        this.opportunityId = opportunityId;
        update(status, notes);
    }
    public void update(ApplicationStatus newStatus, String newNotes) {
        status = newStatus;
        notes = newNotes;
        updatedAt = Instant.now().toString();
    }
    public String getId() { return id; }
    public String getOpportunityId() { return opportunityId; }
    public ApplicationStatus getStatus() { return status; }
    public String getNotes() { return notes; }
    public String getUpdatedAt() { return updatedAt; }
}
