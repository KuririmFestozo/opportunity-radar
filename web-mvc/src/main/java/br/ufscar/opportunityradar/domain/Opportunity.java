package br.ufscar.opportunityradar.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "opportunities")
public class Opportunity {
    @Id
    private String id;

    @Column(nullable = false)
    private String company;
    @Column(nullable = false)
    private String title;
    @Column(columnDefinition = "TEXT")
    private String description;
    @Column(name = "location_text")
    private String locationText;
    @Column(name = "workplace_type")
    private String workplaceType;
    @Column(name = "employment_type")
    private String employmentType;
    @Column(name = "published_at")
    private String publishedAt;
    @Column(name = "canonical_url")
    private String canonicalUrl;
    @Column(name = "updated_at")
    private String updatedAt;

    protected Opportunity() {}

    public String getId() { return id; }
    public String getCompany() { return company; }
    public String getTitle() { return title; }
    public String getDescription() { return description; }
    public String getLocationText() { return locationText; }
    public String getWorkplaceType() { return workplaceType; }
    public String getEmploymentType() { return employmentType; }
    public String getPublishedAt() { return publishedAt; }
    public String getCanonicalUrl() { return canonicalUrl; }
    public String getUpdatedAt() { return updatedAt; }
}
