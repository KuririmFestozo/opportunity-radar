package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.PostingId;
import br.ufscar.opportunityradar.domain.SourcePosting;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface PostingRepository extends JpaRepository<SourcePosting, PostingId> {
    List<SourcePosting> findByOpportunityIdOrderBySourceAsc(String opportunityId);
    @Query("select distinct p.source from SourcePosting p order by p.source")
    List<String> allSources();
}
