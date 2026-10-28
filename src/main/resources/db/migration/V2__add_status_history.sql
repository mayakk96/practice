CREATE TABLE status_history (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES onboarding_case(id),
    previous_status VARCHAR(30) CHECK (previous_status IS NULL OR previous_status IN
        ('CREATED', 'DOCUMENTS_PENDING', 'UNDER_REVIEW', 'RISK_REVIEW', 'APPROVED', 'REJECTED', 'COMPLETED')),
    new_status VARCHAR(30) NOT NULL CHECK (new_status IN
        ('CREATED', 'DOCUMENTS_PENDING', 'UNDER_REVIEW', 'RISK_REVIEW', 'APPROVED', 'REJECTED', 'COMPLETED')),
    reason VARCHAR(500) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX ix_history_case_time ON status_history(case_id, changed_at, id);
