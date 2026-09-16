package dev.supportpilot.ticket;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TicketRepository extends JpaRepository<Ticket, UUID> {
    Optional<Ticket> findByUser_IdAndIdempotencyKey(UUID userId, String idempotencyKey);
    Optional<Ticket> findByIdAndUser_Id(UUID id, UUID userId);
    List<Ticket> findAllByUser_IdOrderByCreatedAtDesc(UUID userId);
}
