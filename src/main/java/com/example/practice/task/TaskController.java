package com.example.practice.task;

import java.net.URI;
import java.util.List;

import jakarta.validation.Valid;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks")
public class TaskController {

    private final TaskRepository repository;

    public TaskController(TaskRepository repository) {
        this.repository = repository;
    }

    @GetMapping
    public List<TaskResponse> list() {
        return repository.findAll(Sort.by("id")).stream().map(TaskResponse::from).toList();
    }

    @GetMapping("/{id}")
    public TaskResponse get(@PathVariable long id) {
        return TaskResponse.from(findTask(id));
    }

    @PostMapping
    public ResponseEntity<TaskResponse> create(@Valid @RequestBody TaskRequest request) {
        Task task = repository.save(new Task(request.title(), request.description(), request.completed()));
        return ResponseEntity.created(URI.create("/api/tasks/" + task.getId())).body(TaskResponse.from(task));
    }

    @PutMapping("/{id}")
    public TaskResponse update(@PathVariable long id, @Valid @RequestBody TaskRequest request) {
        Task task = findTask(id);
        task.update(request.title(), request.description(), request.completed());
        return TaskResponse.from(repository.save(task));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        repository.delete(findTask(id));
        return ResponseEntity.noContent().build();
    }

    private Task findTask(long id) {
        return repository.findById(id).orElseThrow(() -> new TaskNotFoundException(id));
    }
}
