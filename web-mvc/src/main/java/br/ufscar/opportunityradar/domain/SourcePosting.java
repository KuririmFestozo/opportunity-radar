package br.ufscar.opportunityradar.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

@Entity
@IdClass(PostingId.class)
@Table(name = "source_postings")
public class SourcePosting {
    @Id private String source;
    @Id @Column(name = "source_job_id") private String sourceJobId;
    @Column(name = "opportunity_id") private String opportunityId;
    @Column(name = "is_active") private Boolean active;
    @Column(name = "url") private String url;
    @Column(name = "last_seen_at") private String lastSeenAt;
    protected SourcePosting() {}

    public String getSource() { return source; }
    public String getSourceJobId() { return sourceJobId; }
    public String getOpportunityId() { return opportunityId; }
    public Boolean getActive() { return active; }
    public String getUrl() { return url; }
    public String getLastSeenAt() { return lastSeenAt; }
}
