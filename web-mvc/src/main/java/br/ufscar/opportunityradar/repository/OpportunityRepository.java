package br.ufscar.opportunityradar.repository;

import br.ufscar.opportunityradar.domain.Opportunity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

public interface OpportunityRepository extends JpaRepository<Opportunity, String>,
    JpaSpecificationExecutor<Opportunity> {}
