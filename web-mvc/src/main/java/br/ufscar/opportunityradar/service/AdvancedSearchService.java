package br.ufscar.opportunityradar.service;

import br.ufscar.opportunityradar.domain.Opportunity;
import br.ufscar.opportunityradar.repository.OpportunityRepository;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * Read-only search optimized for the existing SQLite catalog.
 *
 * JPA remains the source of mapped Opportunity entities. SQL is only used to
 * select/rank IDs, which avoids loading long descriptions for every candidate.
 * Distance is calculated exactly (Haversine) in Java for geolocated searches.
 */
@Service
public class AdvancedSearchService {
    public record Filters(
        String q, String location, String source, String course, String intent,
        String workplace, String include, String exclude, int minScore,
        boolean activeOnly, String availability, String sort, Double latitude, Double longitude,
        Integer radiusKm, boolean includeRemote, int page
    ) {}

    public record SearchPage(Page<Opportunity> page, Map<String, Integer> affinity,
                             Map<String, Double> distances, Map<String, String> verification, String appliedSort,
                             boolean hasLocation) {}

    private record Candidate(String id, String title, String publishedAt, String updatedAt,
                             String workplace, int score, Double latitude, Double longitude,
                             Double distanceKm, String verification) {
        Candidate withDistance(Double distance) {
            return new Candidate(id, title, publishedAt, updatedAt, workplace,
                score, latitude, longitude, distance, verification);
        }
    }

    private final NamedParameterJdbcTemplate jdbc;
    private final OpportunityRepository opportunities;
    private static final int SIZE = 12;
    private static final double EARTH_RADIUS_KM = 6371.0088;
    private static final long INTENTS_TTL_NANOS = TimeUnit.MINUTES.toNanos(2);
    private volatile List<String> intentsCache;
    private volatile long intentsExpiry;

    public AdvancedSearchService(NamedParameterJdbcTemplate jdbc, OpportunityRepository opportunities) {
        this.jdbc = jdbc;
        this.opportunities = opportunities;
    }

    public SearchPage search(Filters f) {
        int page = Math.max(0, Math.min(f.page(), 10000));
        int score = Math.max(0, Math.min(100, f.minScore()));
        boolean hasLocation = validCoordinates(f.latitude(), f.longitude());
        String sort = switch (f.sort() == null ? "" : f.sort()) {
            case "relevance" -> "relevance";
            case "distance" -> hasLocation ? "distance" : "recent";
            case "title" -> "title";
            default -> "recent";
        };

        MapSqlParameterSource p = new MapSqlParameterSource();
        p.addValue("minScore", score);
        String course = safe(f.course());
        if (course != null) p.addValue("course", course);
        String affinityExpr = course == null
            ? "COALESCE((SELECT MAX(sc.score) FROM opportunity_course_scores sc WHERE sc.opportunity_id = o.id), 0)"
            : "COALESCE((SELECT sc.score FROM opportunity_course_scores sc WHERE sc.opportunity_id = o.id AND sc.course_id = :course), 0)";

        String availability = switch (f.availability() == null ? "" : f.availability()) {
            case "all", "verified", "unverified" -> f.availability();
            default -> "current";
        };
        StringBuilder conditions = new StringBuilder(" WHERE 1=1 ");
        String q = safe(f.q());
        if (q != null) {
            p.addValue("q", pattern(q));
            conditions.append("""
                AND (lower(o.title) LIKE :q ESCAPE '\\'
                  OR lower(o.company) LIKE :q ESCAPE '\\'
                  OR lower(coalesce(o.description,'')) LIKE :q ESCAPE '\\')
                """);
        }
        String location = safe(f.location());
        if (location != null) {
            p.addValue("location", pattern(location));
            conditions.append(" AND lower(o.location_text) LIKE :location ESCAPE '\\' ");
        }
        if (f.activeOnly() || safe(f.source()) != null || !availability.equals("all")) {
            StringBuilder posting = new StringBuilder(
                " AND EXISTS (SELECT 1 FROM source_postings sp "
                + "LEFT JOIN source_availability_checks av "
                + "ON av.source=sp.source AND av.source_job_id=sp.source_job_id "
                + "WHERE sp.opportunity_id=o.id");
            if (f.activeOnly()) posting.append(" AND sp.is_active=1");
            switch (availability) {
                case "current" -> posting.append(
                    " AND COALESCE(av.verdict,'unchecked') NOT IN ('unverified','closed')");
                case "verified" -> posting.append(" AND av.verdict='open'");
                case "unverified" -> posting.append(" AND av.verdict='unverified'");
                default -> { }
            }
            String source = safe(f.source());
            if (source != null) {
                p.addValue("source", source);
                posting.append(" AND sp.source=:source");
            }
            conditions.append(posting).append(") ");
        }
        if (safe(f.intent()) != null && tableExists("opportunity_intents")) {
            p.addValue("intent", safe(f.intent()));
            conditions.append(" AND EXISTS (SELECT 1 FROM opportunity_intents oi "
                + "WHERE oi.opportunity_id=o.id AND oi.intent_id=:intent) ");
        } else if (safe(f.intent()) != null) {
            conditions.append(" AND 1=0 ");
        }
        String workplace = safe(f.workplace());
        if (workplace != null) {
            switch (workplace) {
                case "remote" -> conditions.append(
                    " AND lower(coalesce(o.workplace_type,'')) IN ('remote','remoto','remota') ");
                case "hybrid" -> conditions.append(
                    " AND lower(coalesce(o.workplace_type,'')) IN ('hybrid','hibrido','híbrido') ");
                case "onsite" -> conditions.append(
                    " AND lower(coalesce(o.workplace_type,'')) IN ('onsite','on-site','presencial') ");
                default -> conditions.append(" AND 1=0 ");
            }
        }
        String haystack = "(lower(coalesce(o.title,'')) || ' ' || lower(coalesce(o.company,'')) || "
            + "' ' || lower(coalesce(o.location_text,'')) || ' ' || lower(coalesce(o.description,'')))";
        addTerms(conditions, p, haystack, f.include(), true);
        addTerms(conditions, p, haystack, f.exclude(), false);
        if (course != null) {
            conditions.append(" AND EXISTS (SELECT 1 FROM opportunity_course_scores picked "
                + "WHERE picked.opportunity_id = o.id AND picked.course_id = :course) ");
        }
        if (score > 0) {
            conditions.append(" AND ").append(affinityExpr).append(" >= :minScore ");
        }
        if (hasLocation && f.radiusKm() != null && f.radiusKm() > 0) {
            // SQLite can discard candidates outside a conservative geographic
            // envelope BEFORE calculating exact Haversine distances in Java.
            // Keep remote listings without coordinates when explicitly allowed.
            addGeographicBounds(conditions, p, f.latitude(), f.longitude(),
                Math.min(f.radiusKm(), 1000), f.includeRemote());
        }

        String from = " FROM opportunities o " + conditions;
        String verificationExpr = """
          CASE
            WHEN EXISTS (
              SELECT 1 FROM source_postings pv
              JOIN source_availability_checks v
              ON v.source=pv.source AND v.source_job_id=pv.source_job_id
              WHERE pv.opportunity_id=o.id AND pv.is_active=1 AND v.verdict='open'
            ) THEN 'open'
            WHEN EXISTS (
              SELECT 1 FROM source_postings pv
              JOIN source_availability_checks v
              ON v.source=pv.source AND v.source_job_id=pv.source_job_id
              WHERE pv.opportunity_id=o.id AND pv.is_active=1 AND v.verdict='unverified'
            ) THEN 'unverified'
            WHEN EXISTS (
              SELECT 1 FROM source_postings pv
              JOIN source_availability_checks v
              ON v.source=pv.source AND v.source_job_id=pv.source_job_id
              WHERE pv.opportunity_id=o.id AND v.verdict='closed'
            ) THEN 'closed'
            ELSE 'unchecked'
          END
        """;
        String selection = "SELECT o.id, o.title, o.published_at, o.updated_at, "
            + "o.workplace_type, o.latitude, o.longitude, "
            + affinityExpr + " AS affinity, "
            + verificationExpr + " AS verification " + from;
        String order = switch (sort) {
            case "relevance" -> " ORDER BY affinity DESC, o.updated_at DESC, o.id";
            case "title" -> " ORDER BY o.title COLLATE NOCASE ASC, o.id";
            default -> " ORDER BY o.published_at DESC, o.updated_at DESC, o.id";
        };

        List<Candidate> candidates;
        long total;
        if (hasLocation) {
            // Fetch small metadata rows, not the full JPA entities/descriptions.
            // Calculate real distances before paging, never sort just the visible 12.
            candidates = jdbc.query(selection, p, (rs, rowNum) -> new Candidate(
                rs.getString("id"), rs.getString("title"), rs.getString("published_at"),
                rs.getString("updated_at"), rs.getString("workplace_type"),
                rs.getInt("affinity"), number(rs.getObject("latitude")),
                number(rs.getObject("longitude")), null, rs.getString("verification")));
            List<Candidate> near = new ArrayList<>();
            for (Candidate candidate : candidates) {
                Double distance = candidate.latitude() != null && candidate.longitude() != null
                    ? haversine(f.latitude(), f.longitude(), candidate.latitude(), candidate.longitude())
                    : null;
                boolean remote = candidate.workplace() != null
                    && candidate.workplace().toLowerCase().contains("remot");
                if (f.radiusKm() != null && f.radiusKm() > 0) {
                    int radius = Math.min(f.radiusKm(), 1000);
                    if ((distance == null || distance > radius) && !(f.includeRemote() && remote)) continue;
                }
                near.add(candidate.withDistance(distance));
            }
            candidates = near;
            Comparator<Candidate> orderBy = switch (sort) {
                case "distance" -> Comparator.comparing(Candidate::distanceKm,
                    Comparator.nullsLast(Double::compareTo))
                    .thenComparing(Candidate::score, Comparator.reverseOrder());
                case "relevance" -> Comparator.comparingInt(Candidate::score).reversed()
                    .thenComparing(Candidate::distanceKm, Comparator.nullsLast(Double::compareTo));
                case "title" -> Comparator.comparing(Candidate::title,
                    Comparator.nullsLast(String.CASE_INSENSITIVE_ORDER));
                default -> Comparator.comparing(Candidate::publishedAt,
                    Comparator.nullsFirst(String::compareTo)).reversed();
            };
            candidates.sort(orderBy.thenComparing(Candidate::id));
            total = candidates.size();
            int fromIndex = (int) Math.min(total, (long) page * SIZE);
            candidates = new ArrayList<>(candidates.subList(fromIndex,
                (int) Math.min(total, (long) fromIndex + SIZE)));
        } else {
            total = jdbc.queryForObject("SELECT COUNT(*)" + from, p, Long.class);
            p.addValue("limit", SIZE);
            p.addValue("offset", (long) page * SIZE);
            candidates = jdbc.query(selection + order + " LIMIT :limit OFFSET :offset", p,
                (rs, rowNum) -> new Candidate(
                    rs.getString("id"), rs.getString("title"), rs.getString("published_at"),
                    rs.getString("updated_at"), rs.getString("workplace_type"),
                    rs.getInt("affinity"), number(rs.getObject("latitude")),
                    number(rs.getObject("longitude")), null, rs.getString("verification")));
        }

        List<String> ids = candidates.stream().map(Candidate::id).toList();
        Map<String, Opportunity> entityById = new HashMap<>();
        opportunities.findAllById(ids).forEach(o -> entityById.put(o.getId(), o));
        List<Opportunity> ordered = new ArrayList<>();
        Map<String, Integer> scores = new LinkedHashMap<>();
        Map<String, Double> distances = new LinkedHashMap<>();
        Map<String, String> verification = new LinkedHashMap<>();
        for (Candidate c : candidates) {
            Opportunity item = entityById.get(c.id());
            if (item == null) continue;
            ordered.add(item);
            scores.put(c.id(), c.score());
            verification.put(c.id(), c.verification());
            if (c.distanceKm() != null) {
                distances.put(c.id(), Math.round(c.distanceKm() * 10.0) / 10.0);
            }
        }
        return new SearchPage(new PageImpl<>(ordered, PageRequest.of(page, SIZE), total),
            scores, distances, verification, sort, hasLocation);
    }

    public List<String> intents() {
        List<String> cached = intentsCache;
        long now = System.nanoTime();
        if (cached != null && now < intentsExpiry) return cached;
        synchronized (this) {
            cached = intentsCache;
            now = System.nanoTime();
            if (cached != null && now < intentsExpiry) return cached;
            List<String> values = !tableExists("opportunity_intents") ? List.of()
                : jdbc.getJdbcTemplate().queryForList(
                    "SELECT DISTINCT intent_id FROM opportunity_intents ORDER BY intent_id", String.class);
            cached = List.copyOf(values);
            intentsCache = cached;
            intentsExpiry = System.nanoTime() + INTENTS_TTL_NANOS;
            return cached;
        }
    }

    /**
     * A spherical bounding box is a safe prefilter, never the final distance:
     * antimeridian crossings use an OR, and circles reaching either pole do
     * not restrict longitude. The Java Haversine check remains authoritative.
     */
    private static void addGeographicBounds(StringBuilder sql, MapSqlParameterSource params,
                                            double lat, double lon, int radiusKm,
                                            boolean includeRemote) {
        double angularRadius = radiusKm / EARTH_RADIUS_KM;
        double deltaLatitude = Math.toDegrees(angularRadius);
        double minLat = Math.max(-90, lat - deltaLatitude);
        double maxLat = Math.min(90, lat + deltaLatitude);
        params.addValue("boundMinLat", minLat);
        params.addValue("boundMaxLat", maxLat);
        sql.append(" AND ((o.latitude BETWEEN :boundMinLat AND :boundMaxLat");
        if (minLat > -90 && maxLat < 90) {
            double ratio = Math.sin(angularRadius) / Math.cos(Math.toRadians(lat));
            if (Double.isFinite(ratio) && ratio < 1) {
                double lonDelta = Math.toDegrees(Math.asin(Math.max(0, ratio)));
                double lower = lon - lonDelta;
                double upper = lon + lonDelta;
                if (lower < -180) {
                    params.addValue("boundLo", lower + 360);
                    params.addValue("boundHi", upper);
                    sql.append(" AND (o.longitude >= :boundLo OR o.longitude <= :boundHi)");
                } else if (upper > 180) {
                    params.addValue("boundLo", lower);
                    params.addValue("boundHi", upper - 360);
                    sql.append(" AND (o.longitude >= :boundLo OR o.longitude <= :boundHi)");
                } else {
                    params.addValue("boundLo", lower);
                    params.addValue("boundHi", upper);
                    sql.append(" AND o.longitude BETWEEN :boundLo AND :boundHi");
                }
            }
        }
        sql.append(")");
        if (includeRemote) {
            sql.append(" OR lower(coalesce(o.workplace_type,'')) LIKE '%remot%'");
        }
        sql.append(") ");
    }

    private boolean tableExists(String table) {
        Integer count = jdbc.getJdbcTemplate().queryForObject(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            Integer.class, table);
        return count != null && count > 0;
    }

    private static void addTerms(StringBuilder conditions, MapSqlParameterSource params,
                                 String haystack, String input, boolean include) {
        String[] tokens = input == null ? new String[0] : input.split(",");
        List<String> terms = new ArrayList<>();
        for (String token : tokens) {
            String t = safe(token);
            if (t != null && terms.size() < 4) terms.add(t);
        }
        if (terms.isEmpty()) return;
        if (include) conditions.append(" AND (");
        for (int i = 0; i < terms.size(); i++) {
            String param = (include ? "include" : "exclude") + i;
            params.addValue(param, pattern(terms.get(i)));
            if (include && i > 0) conditions.append(" OR ");
            conditions.append(include ? haystack + " LIKE :" + param + " ESCAPE '\\'"
                : " AND " + haystack + " NOT LIKE :" + param + " ESCAPE '\\'");
        }
        if (include) conditions.append(") ");
    }

    private static String safe(String value) {
        if (value == null || value.isBlank()) return null;
        String trimmed = value.strip();
        return trimmed.substring(0, Math.min(100, trimmed.length()));
    }
    private static String pattern(String input) {
        return "%" + input.toLowerCase().replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_") + "%";
    }
    private static Double number(Object input) {
        return input instanceof Number n ? n.doubleValue() : null;
    }
    private static boolean validCoordinates(Double lat, Double lon) {
        return lat != null && lon != null && Double.isFinite(lat) && Double.isFinite(lon)
            && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }
    public static double haversine(double lat1, double lon1, double lat2, double lon2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLon = Math.toRadians(lon2 - lon1);
        double a = Math.pow(Math.sin(dLat / 2), 2)
            + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
            * Math.pow(Math.sin(dLon / 2), 2);
        return EARTH_RADIUS_KM * 2 * Math.asin(Math.min(1, Math.sqrt(Math.max(0, a))));
    }
}
