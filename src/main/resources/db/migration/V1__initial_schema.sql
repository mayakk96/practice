CREATE TABLE applicant (
    id UUID PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(254) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE onboarding_case (
    id UUID PRIMARY KEY,
    applicant_id UUID NOT NULL REFERENCES applicant(id),
    status VARCHAR(30) NOT NULL CHECK (status IN
        ('CREATED', 'DOCUMENTS_PENDING', 'UNDER_REVIEW', 'RISK_REVIEW', 'APPROVED', 'REJECTED', 'COMPLETED')),
    risk_level VARCHAR(20) NOT NULL CHECK (risk_level IN ('NOT_SCREENED', 'LOW', 'MEDIUM', 'HIGH')),
    assigned_team VARCHAR(40) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    version BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX ix_case_applicant ON onboarding_case(applicant_id);
CREATE INDEX ix_case_created ON onboarding_case(created_at, id);
CREATE INDEX ix_case_status ON onboarding_case(status);

CREATE TABLE case_document (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES onboarding_case(id),
    document_type VARCHAR(30) NOT NULL CHECK (document_type IN ('IDENTITY_PROOF', 'ADDRESS_PROOF')),
    document_reference VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RECEIVED')),
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uk_document_case_type UNIQUE (case_id, document_type)
);

CREATE TABLE idempotency_request (
    request_key VARCHAR(100) PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL,
    case_id UUID REFERENCES onboarding_case(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);
