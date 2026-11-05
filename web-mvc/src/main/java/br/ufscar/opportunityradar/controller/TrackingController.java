package br.ufscar.opportunityradar.controller;

import br.ufscar.opportunityradar.domain.ApplicationStatus;
import br.ufscar.opportunityradar.domain.Opportunity;
import br.ufscar.opportunityradar.service.CatalogService;
import br.ufscar.opportunityradar.service.TrackingService;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class TrackingController {
    private final CatalogService catalog;
    private final TrackingService tracking;

    public TrackingController(CatalogService catalog, TrackingService tracking) {
        this.catalog = catalog;
        this.tracking = tracking;
    }

    @GetMapping("/favorites")
    public String favorites(Model model) {
        var favorites = tracking.favorites();
        Map<String, Opportunity> opportunities = new LinkedHashMap<>();
        for (var favorite : favorites) {
            try { opportunities.put(favorite.getOpportunityId(), catalog.require(favorite.getOpportunityId())); }
            catch (org.springframework.web.server.ResponseStatusException ignored) { }
        }
        model.addAttribute("favorites", favorites);
        model.addAttribute("opportunities", opportunities);
        return "favorites";
    }

    @PostMapping("/favorites/{id}")
    public String toggle(@PathVariable String id, RedirectAttributes flash) {
        tracking.toggleFavorite(id);
        flash.addFlashAttribute("message", "Favoritos atualizados.");
        return "redirect:/opportunities/" + id;
    }

    @GetMapping("/applications")
    public String applications(Model model) {
        var entries = tracking.applications();
        Map<String, Opportunity> opportunities = new LinkedHashMap<>();
        for (var entry : entries) {
            try { opportunities.put(entry.getOpportunityId(), catalog.require(entry.getOpportunityId())); }
            catch (org.springframework.web.server.ResponseStatusException ignored) { }
        }
        model.addAttribute("entries", entries);
        model.addAttribute("opportunities", opportunities);
        model.addAttribute("statuses", ApplicationStatus.values());
        return "applications";
    }

    @PostMapping("/applications/{id}")
    public String save(@PathVariable String id, @RequestParam String status,
                       @RequestParam(defaultValue = "") String notes,
                       RedirectAttributes flash) {
        tracking.saveApplication(id, status, notes);
        flash.addFlashAttribute("message", "Acompanhamento salvo.");
        return "redirect:/opportunities/" + id;
    }

    @PostMapping("/applications/{id}/delete")
    public String delete(@PathVariable String id, RedirectAttributes flash) {
        tracking.deleteApplication(id);
        flash.addFlashAttribute("message", "Acompanhamento removido.");
        return "redirect:/applications";
    }
}
