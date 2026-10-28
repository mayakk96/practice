package com.example.practice.knowledge;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.greaterThan;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
class KnowledgeHttpIntegrationTest {
    @Autowired
    private MockMvc mvc;

    @Test
    void returnsGroundedPolicyEvidenceWithoutAnyExternalModelKey() throws Exception {
        mvc.perform(post("/api/knowledge/search").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"Which documents are required for approval?\",\"topK\":2}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.grounded").value(true))
                .andExpect(jsonPath("$.embeddingModel").value("signed-feature-hash-512"))
                .andExpect(jsonPath("$.answerModel").value("deterministic-extractive-demo"))
                .andExpect(jsonPath("$.citations.length()", greaterThan(0)))
                .andExpect(jsonPath("$.citations[0].source").value("approval-policy.txt"));
    }

    @Test
    void rejectsBlankAndUnboundedQueries() throws Exception {
        mvc.perform(post("/api/knowledge/search").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\" \",\"topK\":2}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.status").value(400));
        mvc.perform(post("/api/knowledge/search").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"approval\",\"topK\":6}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.status").value(400));
    }
}
