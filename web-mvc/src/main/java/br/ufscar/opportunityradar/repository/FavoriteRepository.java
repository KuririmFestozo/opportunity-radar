package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.Favorite;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FavoriteRepository extends JpaRepository<Favorite, String> {
    Optional<Favorite> findByOwnerIdAndOpportunityId(String ownerId, String opportunityId);
    List<Favorite> findAllByOwnerIdOrderByCreatedAtDesc(String ownerId);
    void deleteByOwnerId(String ownerId);
}
