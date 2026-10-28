package com.example.practice.onboarding.repository;

import com.example.practice.onboarding.model.Applicant;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApplicantRepository extends JpaRepository<Applicant, UUID> {
}
