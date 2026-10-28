package com.example.practice.onboarding;

import com.example.practice.onboarding.model.IdempotencyRequest;
import com.example.practice.onboarding.repository.IdempotencyRequestRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mockingDetails;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Forces the race where another request commits after lookup but before claim insertion. */
@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:claim-race-regression;MODE=PostgreSQL;"
        + "DATABASE_TO_LOWER=TRUE;DEFAULT_NULL_ORDERING=HIGH;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000")
@ActiveProfiles("test")
@AutoConfigureMockMvc
class IdempotencyClaimRaceIntegrationTest {
    private static final String CASES = "/api/onboarding/cases";

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper json;

    @Autowired
    private JdbcTemplate jdbc;

    @MockitoSpyBean
    private IdempotencyRequestRepository requests;

    @Test
    void winnerCommittedBetweenLookupAndInsertCannotBeMergedIntoANewClaim() throws Exception {
        CountDownLatch loserReadyToInsert = new CountDownLatch(1);
        CountDownLatch releaseLoser = new CountDownLatch(1);
        AtomicBoolean pauseFirstClaim = new AtomicBoolean(true);
        // Spring Data repositories are proxies. Preserve the spy's original delegate
        // answer instead of invoking an abstract repository interface method directly.
        Answer<?> realRepository = mockingDetails(requests).getMockCreationSettings().getDefaultAnswer();
        doAnswer(invocation -> {
            if (pauseFirstClaim.compareAndSet(true, false)) {
                loserReadyToInsert.countDown();
                if (!releaseLoser.await(15, TimeUnit.SECONDS)) {
                    throw new AssertionError("Timed out waiting for the winning request to commit");
                }
            }
            return realRepository.answer(invocation);
        }).when(requests).saveAndFlush(any(IdempotencyRequest.class));

        String key = UUID.randomUUID().toString();
        String body = """
                {"firstName":"Demo","lastName":"ClaimRace","email":"claim-race@example.com"}
                """;
        try (var executor = Executors.newSingleThreadExecutor()) {
            var loser = executor.submit(() -> mvc.perform(post(CASES)
                            .header("Idempotency-Key", key)
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andReturn());
            try {
                assertThat(loserReadyToInsert.await(5, TimeUnit.SECONDS)).isTrue();
                var winner = mvc.perform(post(CASES).header("Idempotency-Key", key)
                                .contentType(MediaType.APPLICATION_JSON).content(body))
                        .andExpect(status().isCreated()).andReturn();
                String winnerId = json.readTree(winner.getResponse().getContentAsString()).path("id").asText();

                // The second request has now committed its claim, case, history and event.
                releaseLoser.countDown();
                var replay = loser.get(20, TimeUnit.SECONDS);
                assertThat(replay.getResponse().getStatus()).isEqualTo(200);
                assertThat(replay.getResponse().getHeader("Idempotency-Replayed")).isEqualTo("true");
                assertThat(json.readTree(replay.getResponse().getContentAsString()).path("id").asText())
                        .isEqualTo(winnerId);

                assertThat(jdbc.queryForObject("SELECT count(*) FROM applicant", Long.class)).isEqualTo(1);
                assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
                assertThat(jdbc.queryForObject("SELECT count(*) FROM event_outbox", Long.class)).isEqualTo(1);
                assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_request", Long.class)).isEqualTo(1);
                assertThat(requests.findById(key).orElseThrow().getCaseId()).isEqualTo(UUID.fromString(winnerId));
            } finally {
                releaseLoser.countDown();
            }
        }
    }
}
