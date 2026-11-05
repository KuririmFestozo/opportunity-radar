package br.ufscar.opportunityradar.domain;

import java.io.Serializable;
import java.util.Objects;

public class PostingId implements Serializable {
    private String source;
    private String sourceJobId;

    public PostingId() {}
    public PostingId(String source, String sourceJobId) {
        this.source = source;
        this.sourceJobId = sourceJobId;
    }
    @Override public boolean equals(Object object) {
        return object instanceof PostingId other
            && Objects.equals(source, other.source)
            && Objects.equals(sourceJobId, other.sourceJobId);
    }
    @Override public int hashCode() { return Objects.hash(source, sourceJobId); }
}
