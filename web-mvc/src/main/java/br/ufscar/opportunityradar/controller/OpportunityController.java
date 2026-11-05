package br.ufscar.opportunityradar.controller;

import br.ufscar.opportunityradar.domain.ApplicationStatus;
import br.ufscar.opportunityradar.service.CatalogService;
import br.ufscar.opportunityradar.service.TrackingService;
import org.springframework.data.domain.Page;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
public class OpportunityController {
    private final CatalogService catalog;
    private final TrackingService tracking;

    public OpportunityController(CatalogService catalog, TrackingService tracking) {
        this.catalog = catalog;
        this.tracking = tracking;
    }

    @GetMapping("/")
    public String home() { return "redirect:/opportunities"; }

    @GetMapping("/opportunities")
    public String list(@RequestParam(defaultValue = "") String q,
                       @RequestParam(defaultValue = "") String location,
                       @RequestParam(defaultValue = "") String source,
                       @RequestParam(defaultValue = "") String course,
                       @RequestParam(defaultValue = "0") int minScore,
                       @RequestParam(defaultValue = "true") boolean activeOnly,
                       @RequestParam(defaultValue = "0") int page, Model model) {
        var results = catalog.search(q, location, source, course, minScore, activeOnly, page);
        model.addAttribute("results", results);
        model.addAttribute("q", q);
        model.addAttribute("location", location);
        model.addAttribute("source", source);
        model.addAttribute("course", course);
        model.addAttribute("minScore", minScore);
        model.addAttribute("activeOnly", activeOnly);
        model.addAttribute("sources", catalog.sources());
        model.addAttribute("courses", catalog.courses());
        model.addAttribute("total", catalog.total());
        return "opportunities";
    }

    @GetMapping("/opportunities/{id}")
    public String detail(@PathVariable String id, Model model) {
        var opportunity = catalog.require(id);
        model.addAttribute("opportunity", opportunity);
        model.addAttribute("postings", catalog.postings(id));
        model.addAttribute("scores", catalog.scores(id));
        model.addAttribute("favorite", tracking.isFavorite(id));
        model.addAttribute("application", tracking.applicationFor(id).orElse(null));
        model.addAttribute("statuses", ApplicationStatus.values());
        model.addAttribute("safeUrl", CatalogService.safeUrl(opportunity.getCanonicalUrl()));
        return "detail";
    }
}
