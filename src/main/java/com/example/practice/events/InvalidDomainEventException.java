package com.example.practice.events;

public class InvalidDomainEventException extends RuntimeException {
    public InvalidDomainEventException(String message) {
        super(message);
    }
}
