package com.example.practice.task;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:task-tests;DB_CLOSE_DELAY=-1",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
@AutoConfigureMockMvc
class TaskApiIntegrationTest {

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private TaskRepository repository;

    @BeforeEach
    void clearDatabase() {
        repository.deleteAll();
    }

    @Test
    void listsAnEmptyDatabase() throws Exception {
        mvc.perform(get("/api/tasks"))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
    }

    @Test
    void createsReadsUpdatesAndDeletesATask() throws Exception {
        JsonNode created = createTask(Map.of(
                "title", "Learn Spring Boot",
                "description", "Build a REST API",
                "completed", false));
        long id = created.path("id").asLong();

        assertThat(id).isPositive();
        assertThat(repository.existsById(id)).isTrue();
        assertThat(repository.count()).isEqualTo(1);

        mvc.perform(get("/api/tasks/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(id))
                .andExpect(jsonPath("$.title").value("Learn Spring Boot"))
                .andExpect(jsonPath("$.description").value("Build a REST API"))
                .andExpect(jsonPath("$.completed").value(false));

        mvc.perform(put("/api/tasks/{id}", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "title", "Ship the API",
                                "description", "Tests are passing",
                                "completed", true))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(id))
                .andExpect(jsonPath("$.title").value("Ship the API"))
                .andExpect(jsonPath("$.description").value("Tests are passing"))
                .andExpect(jsonPath("$.completed").value(true));

        // A separate request reads the committed update from the real database.
        mvc.perform(get("/api/tasks/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("Ship the API"))
                .andExpect(jsonPath("$.completed").value(true));
        assertThat(repository.count()).isEqualTo(1);

        mvc.perform(delete("/api/tasks/{id}", id))
                .andExpect(status().isNoContent())
                .andExpect(content().string(""));

        assertThat(repository.existsById(id)).isFalse();
        assertThat(repository.count()).isZero();
        mvc.perform(get("/api/tasks/{id}", id)).andExpect(status().isNotFound());
    }

    @Test
    void defaultsCompletedToFalseWhenOnlyTitleIsProvided() throws Exception {
        JsonNode created = createTask(Map.of("title", "A new task"));

        assertThat(created.path("title").asText()).isEqualTo("A new task");
        assertThat(created.path("completed").isBoolean()).isTrue();
        assertThat(created.path("completed").asBoolean()).isFalse();
        assertThat(repository.existsById(created.path("id").asLong())).isTrue();
    }

    @Test
    void listsTasksInAscendingIdOrder() throws Exception {
        long firstId = createTask(Map.of("title", "First")).path("id").asLong();
        long secondId = createTask(Map.of("title", "Second")).path("id").asLong();

        mvc.perform(get("/api/tasks"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].id").value(firstId))
                .andExpect(jsonPath("$[0].title").value("First"))
                .andExpect(jsonPath("$[1].id").value(secondId))
                .andExpect(jsonPath("$[1].title").value("Second"));
    }

    @ParameterizedTest
    @MethodSource("invalidTitles")
    void rejectsBlankOrOversizedTitles(String title) throws Exception {
        mvc.perform(post("/api/tasks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("title", title))))
                .andExpect(status().isBadRequest());

        assertThat(repository.count()).isZero();
    }

    static Stream<String> invalidTitles() {
        return Stream.of("", "   ", "x".repeat(121));
    }

    @Test
    void rejectsMissingTitles() throws Exception {
        mvc.perform(post("/api/tasks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"description\":\"No title\"}"))
                .andExpect(status().isBadRequest());

        assertThat(repository.count()).isZero();
    }

    @Test
    void rejectsOversizedDescriptions() throws Exception {
        mvc.perform(post("/api/tasks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "title", "Valid title",
                                "description", "x".repeat(2001)))))
                .andExpect(status().isBadRequest());

        assertThat(repository.count()).isZero();
    }

    @Test
    void rejectsMalformedJson() throws Exception {
        mvc.perform(post("/api/tasks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{"))
                .andExpect(status().isBadRequest());

        assertThat(repository.count()).isZero();
    }

    @Test
    void returnsNotFoundForMissingTasks() throws Exception {
        long missingId = Long.MAX_VALUE;

        mvc.perform(get("/api/tasks/{id}", missingId)).andExpect(status().isNotFound());
        mvc.perform(put("/api/tasks/{id}", missingId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"Missing task\",\"completed\":true}"))
                .andExpect(status().isNotFound());
        mvc.perform(delete("/api/tasks/{id}", missingId)).andExpect(status().isNotFound());

        assertThat(repository.count()).isZero();
    }

    private JsonNode createTask(Map<String, ?> request) throws Exception {
        MvcResult result = mvc.perform(post("/api/tasks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber())
                .andReturn();
        JsonNode created = objectMapper.readTree(result.getResponse().getContentAsString());
        String location = result.getResponse().getHeader("Location");
        assertThat(location).endsWith("/api/tasks/" + created.path("id").asLong());
        return created;
    }
}
