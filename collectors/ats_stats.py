"""Per-run counters for public ATS searches; never a persistent watermark."""

from collectors.corporate_ats import JobRef, _is_priority_ref
from processing.incremental import report_incremental


class SearchStats:
    def __init__(self, config, queries):
        self.config = config
        self.queries = queries
        self.raw = 0
        self.unique = set()
        self.early = set()
        self.query_scoped = set()
        self.eligible = set()
        self.progress = {}
        self.repeated = set()
        self.bounded = set()

    def page(self, query, size, total):
        self.raw += size
        previous = self.progress.get(query, (0, None))[0]
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = None
        self.progress[query] = (previous + size, total)

    def admit(self, job, *, query_scoped=False):
        self.unique.add(job.source_job_id)
        title = f"{job.title} {job.employment_type or ''}"
        early = _is_priority_ref(JobRef(job.source_job_id, title, job.url))
        if early:
            self.early.add(job.source_job_id)
        if query_scoped:
            self.query_scoped.add(job.source_job_id)

        # Explicit early-career queries define source/product scope. The source
        # may have matched description/metadata that is absent from the card.
        allowed = (
            query_scoped
            or early
            or not self.config.get("early_career_only", False)
        )
        if allowed:
            self.eligible.add(job.source_job_id)
        return allowed

    def report(self, jobs, requests):
        jobs = list(jobs)
        report_incremental(self.config, jobs, requests)

        configured_cap = int(self.config.get("max_jobs", 0) or 0)
        cap_label = str(configured_cap) if configured_cap > 0 else "sem teto configurado"

        if self.config.get("show_incremental_stats"):
            print(
                f"[SCOPE] {self.config['name']}: {self.raw} refs brutas | "
                f"{len(self.unique)} únicas | "
                f"{len(self.early)} early-career pelo título/tipo | "
                f"{len(self.query_scoped)} retornadas por query explícita | "
                f"{len(jobs)} retornadas | teto {cap_label} | {requests} requests"
            )

        unvisited = len(set(self.queries) - self.progress.keys())
        unread = sum(
            max(0, total - read)
            for read, total in self.progress.values()
            if total is not None
        )
        returned = {job.source_job_id for job in jobs}
        omitted = len(self.eligible - returned)
        unknown = sum(total is None for read, total in self.progress.values())

        if omitted or unread or unvisited or self.repeated or self.bounded:
            print(
                f"[LIMIT] {self.config['name']}: "
                f"{omitted} elegíveis observadas fora do teto; "
                f"até {unread} refs não percorridas nas consultas com total informado "
                f"(podem se sobrepor); {unvisited} consultas não executadas; "
                f"{len(self.repeated)} consultas com página repetida; "
                f"{len(self.bounded)} consultas limitadas por páginas; "
                f"{unknown} totais desconhecidos. "
                "Total único omitido indeterminado."
            )
