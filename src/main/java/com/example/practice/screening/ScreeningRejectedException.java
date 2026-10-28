package com.example.practice.screening;

public class ScreeningRejectedException extends RuntimeException {
    public ScreeningRejectedException(String message) {
        super(message);
    }
}
