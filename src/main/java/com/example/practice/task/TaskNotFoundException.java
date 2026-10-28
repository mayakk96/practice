package com.example.practice.task;

class TaskNotFoundException extends RuntimeException {

    TaskNotFoundException(long id) {
        super("Task " + id + " was not found.");
    }
}
