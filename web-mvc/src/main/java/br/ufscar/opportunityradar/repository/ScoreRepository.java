package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.CourseScore;
import br.ufscar.opportunityradar.domain.CourseScoreId;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface ScoreRepository extends JpaRepository<CourseScore, CourseScoreId> {
    List<CourseScore> findByOpportunityIdOrderByScoreDesc(String opportunityId);
    @Query("select distinct c.courseId from CourseScore c order by c.courseId")
    List<String> allCourses();
}
