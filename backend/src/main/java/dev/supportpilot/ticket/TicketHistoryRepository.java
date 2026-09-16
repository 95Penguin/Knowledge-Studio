package dev.supportpilot.ticket;

import java.util.UUID;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TicketHistoryRepository extends JpaRepository<TicketHistory, UUID> {
    List<TicketHistory> findAllByTicket_IdOrderByCreatedAtAsc(UUID ticketId);
}
