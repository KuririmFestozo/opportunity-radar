package br.ufscar.opportunityradar.domain;

import java.io.Serializable;
import java.util.Objects;

public class CourseScoreId implements Serializable {
    private String opportunityId;
    private String courseId;
    public CourseScoreId() {}
    public CourseScoreId(String opportunityId, String courseId) {
        this.opportunityId = opportunityId;
        this.courseId = courseId;
    }
    @Override public boolean equals(Object object) {
        return object instanceof CourseScoreId other
            && Objects.equals(opportunityId, other.opportunityId)
            && Objects.equals(courseId, other.courseId);
    }
    @Override public int hashCode() { return Objects.hash(opportunityId, courseId); }
}
