package br.ufscar.opportunityradar.service;

import br.ufscar.opportunityradar.domain.ApplicationEntry;
import br.ufscar.opportunityradar.domain.ApplicationStatus;
import br.ufscar.opportunityradar.domain.Favorite;
import br.ufscar.opportunityradar.repository.ApplicationRepository;
import br.ufscar.opportunityradar.repository.FavoriteRepository;

import java.util.List;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class TrackingService {
    private final CatalogService catalog;
    private final FavoriteRepository favorites;
    private final ApplicationRepository applications;

    public TrackingService(CatalogService catalog, FavoriteRepository favorites,
                           ApplicationRepository applications) {
        this.catalog = catalog;
        this.favorites = favorites;
        this.applications = applications;
    }

    @Transactional
    public void toggleFavorite(String opportunityId) {
        catalog.require(opportunityId);
        favorites.findByOpportunityId(opportunityId)
            .ifPresentOrElse(favorites::delete, () -> favorites.save(new Favorite(opportunityId)));
    }
    public boolean isFavorite(String opportunityId) {
        return favorites.findByOpportunityId(opportunityId).isPresent();
    }
    public List<Favorite> favorites() { return favorites.findAllByOrderByCreatedAtDesc(); }
    public List<ApplicationEntry> applications() { return applications.findAllByOrderByUpdatedAtDesc(); }
    public Optional<ApplicationEntry> applicationFor(String opportunityId) {
        return applications.findByOpportunityId(opportunityId);
    }

    @Transactional
    public void saveApplication(String opportunityId, String statusValue, String notes) {
        catalog.require(opportunityId);
        ApplicationStatus status;
        try {
            status = ApplicationStatus.valueOf(statusValue);
        } catch (IllegalArgumentException | NullPointerException exc) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Status invalido");
        }
        if (notes != null && notes.length() > 2000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Notas excedem 2000 caracteres");
        }
        String safeNotes = notes == null ? "" : notes.strip();
        ApplicationEntry entry = applications.findByOpportunityId(opportunityId)
            .orElseGet(() -> new ApplicationEntry(opportunityId, status, safeNotes));
        entry.update(status, safeNotes);
        applications.save(entry);
    }

    @Transactional
    public void deleteApplication(String opportunityId) {
        applications.findByOpportunityId(opportunityId).ifPresent(applications::delete);
    }
}
