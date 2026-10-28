package com.example.practice.screening;

import java.util.UUID;

/** A business-facing boundary; callers do not depend on HTTP or a particular provider. */
public interface RiskScreeningClient {
    ScreeningResult screen(UUID caseId);
}
