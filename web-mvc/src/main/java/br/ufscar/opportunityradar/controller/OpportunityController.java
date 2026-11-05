package br.ufscar.opportunityradar.controller;

import br.ufscar.opportunityradar.config.VisitorIdentityFilter;
import br.ufscar.opportunityradar.domain.ApplicationStatus;
import br.ufscar.opportunityradar.service.AdvancedSearchService;
import br.ufscar.opportunityradar.service.CatalogService;
import br.ufscar.opportunityradar.service.TrackingService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
public class OpportunityController {
    private final CatalogService catalog;
    private final TrackingService tracking;
    private final AdvancedSearchService advanced;

    public OpportunityController(CatalogService catalog, TrackingService tracking,
                                 AdvancedSearchService advanced) {
        this.catalog = catalog;
        this.tracking = tracking;
        this.advanced = advanced;
    }

    @GetMapping("/")
    public String home() { return "redirect:/opportunities"; }

    @GetMapping("/opportunities")
    public String list(@RequestParam(defaultValue = "") String q,
                       @RequestParam(defaultValue = "") String location,
                       @RequestParam(defaultValue = "") String source,
                       @RequestParam(defaultValue = "") String course,
                       @RequestParam(defaultValue = "") String intent,
                       @RequestParam(defaultValue = "") String workplace,
                       @RequestParam(defaultValue = "") String include,
                       @RequestParam(defaultValue = "") String exclude,
                       @RequestParam(defaultValue = "0") int minScore,
                       @RequestParam(defaultValue = "true") boolean activeOnly,
                       @RequestParam(defaultValue = "relevance") String sort,
                       @RequestParam(required = false) Double latitude,
                       @RequestParam(required = false) Double longitude,
                       @RequestParam(required = false) Integer radiusKm,
                       @RequestParam(defaultValue = "false") boolean includeRemote,
                       @RequestParam(defaultValue = "0") int page, Model model) {
        var found = advanced.search(new AdvancedSearchService.Filters(
            q, location, source, course, intent, workplace, include, exclude,
            minScore, activeOnly, sort, latitude, longitude, radiusKm, includeRemote, page));
        model.addAttribute("results", found.page());
        model.addAttribute("affinity", found.affinity());
        model.addAttribute("distances", found.distances());
        model.addAttribute("appliedSort", found.appliedSort());
        model.addAttribute("hasLocation", found.hasLocation());
        model.addAttribute("q", q);
        model.addAttribute("location", location);
        model.addAttribute("source", source);
        model.addAttribute("course", course);
        model.addAttribute("intent", intent);
        model.addAttribute("workplace", workplace);
        model.addAttribute("include", include);
        model.addAttribute("exclude", exclude);
        model.addAttribute("minScore", minScore);
        model.addAttribute("activeOnly", activeOnly);
        model.addAttribute("sort", sort);
        model.addAttribute("latitude", latitude);
        model.addAttribute("longitude", longitude);
        model.addAttribute("radiusKm", radiusKm);
        model.addAttribute("includeRemote", includeRemote);
        model.addAttribute("sources", catalog.sources());
        model.addAttribute("courses", catalog.courses());
        model.addAttribute("intents", advanced.intents());
        model.addAttribute("total", catalog.total());
        return "opportunities";
    }

    @GetMapping("/opportunities/{id}")
    public String detail(@PathVariable String id,
                         @RequestAttribute(VisitorIdentityFilter.ATTRIBUTE) String visitor,
                         Model model) {
        var opportunity = catalog.require(id);
        model.addAttribute("opportunity", opportunity);
        model.addAttribute("postings", catalog.postings(id));
        model.addAttribute("scores", catalog.scores(id));
        model.addAttribute("favorite", tracking.isFavorite(visitor, id));
        model.addAttribute("application", tracking.applicationFor(visitor, id).orElse(null));
        model.addAttribute("statuses", ApplicationStatus.values());
        model.addAttribute("safeUrl", CatalogService.safeUrl(opportunity.getCanonicalUrl()));
        return "detail";
    }
}
