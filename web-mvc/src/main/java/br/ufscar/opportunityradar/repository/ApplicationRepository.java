package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.ApplicationEntry;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApplicationRepository extends JpaRepository<ApplicationEntry, String> {
    Optional<ApplicationEntry> findByOwnerIdAndOpportunityId(String ownerId, String opportunityId);
    List<ApplicationEntry> findAllByOwnerIdOrderByUpdatedAtDesc(String ownerId);
    void deleteByOwnerId(String ownerId);
}
