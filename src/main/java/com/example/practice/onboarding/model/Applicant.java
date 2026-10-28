package com.example.practice.onboarding.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "applicant")
public class Applicant {
    @Id
    private UUID id;
    @Column(name = "first_name", nullable = false, length = 80)
    private String firstName;
    @Column(name = "last_name", nullable = false, length = 80)
    private String lastName;
    @Column(nullable = false, length = 254)
    private String email;
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected Applicant() { }

    public Applicant(String firstName, String lastName, String email, Instant now) {
        this.id = UUID.randomUUID();
        this.firstName = firstName;
        this.lastName = lastName;
        this.email = email;
        this.createdAt = now;
    }

    public UUID getId() { return id; }
    public String getFirstName() { return firstName; }
    public String getLastName() { return lastName; }
    public String getEmail() { return email; }
    public Instant getCreatedAt() { return createdAt; }
}
