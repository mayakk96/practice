package com.example.practice.events;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface OutboxEventRepository extends JpaRepository<OutboxEvent, UUID> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select event from OutboxEvent event
            where event.publishedAt is null and event.nextAttemptAt <= :now
            and not exists (
                select older.id from OutboxEvent older
                where older.caseId = event.caseId and older.publishedAt is null
                and older.sequenceNumber < event.sequenceNumber
            )
            order by event.sequenceNumber
            """)
    List<OutboxEvent> lockNextDeliverable(@Param("now") Instant now, Pageable page);

    long countByPublishedAtIsNull();
}
