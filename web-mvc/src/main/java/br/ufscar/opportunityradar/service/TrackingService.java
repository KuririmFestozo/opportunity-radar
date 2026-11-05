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
    public void toggleFavorite(String ownerId, String opportunityId) {
        catalog.require(opportunityId);
        favorites.findByOwnerIdAndOpportunityId(ownerId, opportunityId)
            .ifPresentOrElse(favorites::delete, () -> favorites.save(new Favorite(ownerId, opportunityId)));
    }
    public boolean isFavorite(String ownerId, String opportunityId) {
        return favorites.findByOwnerIdAndOpportunityId(ownerId, opportunityId).isPresent();
    }
    public List<Favorite> favorites(String ownerId) {
        return favorites.findAllByOwnerIdOrderByCreatedAtDesc(ownerId);
    }
    public List<ApplicationEntry> applications(String ownerId) {
        return applications.findAllByOwnerIdOrderByUpdatedAtDesc(ownerId);
    }
    public Optional<ApplicationEntry> applicationFor(String ownerId, String opportunityId) {
        return applications.findByOwnerIdAndOpportunityId(ownerId, opportunityId);
    }

    @Transactional
    public void saveApplication(String ownerId, String opportunityId, String statusValue, String notes) {
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
        ApplicationEntry entry = applications.findByOwnerIdAndOpportunityId(ownerId, opportunityId)
            .orElseGet(() -> new ApplicationEntry(ownerId, opportunityId, status, safeNotes));
        entry.update(status, safeNotes);
        applications.save(entry);
    }

    @Transactional
    public void deleteApplication(String ownerId, String opportunityId) {
        applications.findByOwnerIdAndOpportunityId(ownerId, opportunityId)
            .ifPresent(applications::delete);
    }
}
