package br.ufscar.opportunityradar.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

@Entity
@IdClass(CourseScoreId.class)
@Table(name = "opportunity_course_scores")
public class CourseScore {
    @Id @Column(name = "opportunity_id") private String opportunityId;
    @Id @Column(name = "course_id") private String courseId;
    private Integer score;
    protected CourseScore() {}
    public String getOpportunityId() { return opportunityId; }
    public String getCourseId() { return courseId; }
    public Integer getScore() { return score; }
}
