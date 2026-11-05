package br.ufscar.opportunityradar.service;

import br.ufscar.opportunityradar.domain.CourseScore;
import br.ufscar.opportunityradar.domain.Opportunity;
import br.ufscar.opportunityradar.domain.SourcePosting;
import br.ufscar.opportunityradar.repository.OpportunityRepository;
import br.ufscar.opportunityradar.repository.PostingRepository;
import br.ufscar.opportunityradar.repository.ScoreRepository;

import jakarta.persistence.criteria.Root;
import jakarta.persistence.criteria.Subquery;
import java.net.URI;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class CatalogService {
    private final OpportunityRepository opportunities;
    private final PostingRepository postings;
    private final ScoreRepository scores;

    public CatalogService(OpportunityRepository opportunities, PostingRepository postings,
                          ScoreRepository scores) {
        this.opportunities = opportunities;
        this.postings = postings;
        this.scores = scores;
    }

    public Page<Opportunity> search(String text, String location, String source,
                                    String course, int minScore, boolean activeOnly, int page) {
        String q = normalized(text);
        String loc = normalized(location);
        String src = normalized(source);
        String courseId = normalized(course);
        int safeScore = Math.max(0, Math.min(100, minScore));
        Specification<Opportunity> filters = (root, query, cb) -> {
            var all = cb.conjunction();
            if (q != null) {
                String pattern = "%" + escapeLike(q.toLowerCase()) + "%";
                all = cb.and(all, cb.or(
                    cb.like(cb.lower(root.get("title")), pattern, '\\'),
                    cb.like(cb.lower(root.get("company")), pattern, '\\'),
                    cb.like(cb.lower(root.get("description")), pattern, '\\')));
            }
            if (loc != null) {
                all = cb.and(all, cb.like(cb.lower(root.get("locationText")),
                    "%" + escapeLike(loc.toLowerCase()) + "%", '\\'));
            }
            if (activeOnly || src != null) {
                Subquery<Integer> postingMatch = query.subquery(Integer.class);
                Root<SourcePosting> posting = postingMatch.from(SourcePosting.class);
                var restriction = cb.equal(posting.get("opportunityId"), root.get("id"));
                if (activeOnly) restriction = cb.and(restriction, cb.isTrue(posting.get("active")));
                if (src != null) restriction = cb.and(restriction, cb.equal(posting.get("source"), src));
                postingMatch.select(cb.literal(1)).where(restriction);
                all = cb.and(all, cb.exists(postingMatch));
            }
            if (courseId != null) {
                Subquery<Integer> courseMatch = query.subquery(Integer.class);
                Root<CourseScore> score = courseMatch.from(CourseScore.class);
                courseMatch.select(cb.literal(1)).where(
                    cb.equal(score.get("opportunityId"), root.get("id")),
                    cb.equal(score.get("courseId"), courseId),
                    cb.greaterThanOrEqualTo(score.get("score"), safeScore));
                all = cb.and(all, cb.exists(courseMatch));
            }
            return all;
        };
        return opportunities.findAll(filters,
            PageRequest.of(Math.max(0, Math.min(page, 100000)), 12,
                Sort.by(Sort.Direction.DESC, "updatedAt")));
    }

    public Opportunity require(String id) {
        return opportunities.findById(id).orElseThrow(
            () -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Oportunidade nao encontrada"));
    }

    public List<SourcePosting> postings(String opportunityId) {
        return postings.findByOpportunityIdOrderBySourceAsc(opportunityId);
    }
    public List<CourseScore> scores(String opportunityId) {
        return scores.findByOpportunityIdOrderByScoreDesc(opportunityId);
    }
    public List<String> sources() { return postings.allSources(); }
    public List<String> courses() { return scores.allCourses(); }
    public long total() { return opportunities.count(); }

    public static String safeUrl(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            URI uri = URI.create(value.trim());
            if (!("https".equalsIgnoreCase(uri.getScheme())
                  || "http".equalsIgnoreCase(uri.getScheme()))
                || uri.getHost() == null) return null;
            return uri.toASCIIString();
        } catch (IllegalArgumentException ex) {
            return null;
        }
    }
    private static String normalized(String s) {
        if (s == null || s.isBlank()) return null;
        return s.strip().substring(0, Math.min(s.strip().length(), 100));
    }
    private static String escapeLike(String s) {
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
