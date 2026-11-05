package br.ufscar.opportunityradar.domain;

public enum ApplicationStatus {
    PLANNED("Planejada"), APPLIED("Candidatado"),
    INTERVIEW("Entrevista"), OFFER("Proposta"), REJECTED("Encerrada");

    private final String label;
    ApplicationStatus(String label) { this.label = label; }
    public String getLabel() { return label; }
}
