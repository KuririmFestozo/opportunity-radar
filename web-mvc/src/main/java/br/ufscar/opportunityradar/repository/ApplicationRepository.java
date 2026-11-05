package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.ApplicationEntry;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApplicationRepository extends JpaRepository<ApplicationEntry, String> {
    Optional<ApplicationEntry> findByOpportunityId(String opportunityId);
    List<ApplicationEntry> findAllByOrderByUpdatedAtDesc();
}
