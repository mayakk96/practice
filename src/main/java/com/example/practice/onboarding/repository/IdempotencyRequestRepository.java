package com.example.practice.onboarding.repository;

import com.example.practice.onboarding.model.IdempotencyRequest;
import org.springframework.data.jpa.repository.JpaRepository;

public interface IdempotencyRequestRepository extends JpaRepository<IdempotencyRequest, String> {
}
