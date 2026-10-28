package com.example.practice.task;

public record TaskResponse(Long id, String title, String description, boolean completed) {

    static TaskResponse from(Task task) {
        return new TaskResponse(task.getId(), task.getTitle(), task.getDescription(), task.isCompleted());
    }
}
