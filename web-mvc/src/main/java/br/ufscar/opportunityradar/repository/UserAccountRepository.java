package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.UserAccount;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserAccountRepository extends JpaRepository<UserAccount, String> {
    Optional<UserAccount> findByUsername(String username);
    boolean existsByUsername(String username);
}
