package br.ufscar.opportunityradar.service;

import br.ufscar.opportunityradar.domain.ApplicationEntry;
import br.ufscar.opportunityradar.domain.Favorite;
import br.ufscar.opportunityradar.repository.ApplicationRepository;
import br.ufscar.opportunityradar.repository.FavoriteRepository;
import java.security.Principal;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * On the first successful sign-in, move the current browser's legacy
 * anonymous favorites/application notes to the authenticated account.
 * Other browsers' data is never touched.
 */
@Service
public class AccountMigrationService {
    private final AccountService accounts;
    private final FavoriteRepository favorites;
    private final ApplicationRepository applications;

    public AccountMigrationService(AccountService accounts, FavoriteRepository favorites,
                                   ApplicationRepository applications) {
        this.accounts = accounts;
        this.favorites = favorites;
        this.applications = applications;
    }

    @Transactional
    public void importBrowserData(Principal principal, String anonymousId) {
        if (anonymousId == null || !anonymousId.matches("[a-f0-9]{64}")) return;
        String ownerId = accounts.ownerId(principal);
        for (Favorite previous : favorites.findAllByOwnerIdOrderByCreatedAtDesc(anonymousId)) {
            if (favorites.findByOwnerIdAndOpportunityId(ownerId, previous.getOpportunityId()).isEmpty()) {
                favorites.save(new Favorite(ownerId, previous.getOpportunityId()));
            }
        }
        for (ApplicationEntry previous : applications.findAllByOwnerIdOrderByUpdatedAtDesc(anonymousId)) {
            if (applications.findByOwnerIdAndOpportunityId(ownerId, previous.getOpportunityId()).isEmpty()) {
                applications.save(new ApplicationEntry(ownerId, previous.getOpportunityId(),
                    previous.getStatus(), previous.getNotes()));
            }
        }
        // Atomically eliminate old anonymous access to imported entries.
        favorites.deleteByOwnerId(anonymousId);
        applications.deleteByOwnerId(anonymousId);
    }
}
