package dev.supportpilot.ticket;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "ticket_history")
public class TicketHistory {
    @Id @GeneratedValue private UUID id;
    @ManyToOne(optional = false) @JoinColumn(name = "ticket_id") private Ticket ticket;
    @Enumerated(EnumType.STRING) private TicketStatus fromStatus;
    @Enumerated(EnumType.STRING) @Column(nullable = false) private TicketStatus toStatus;
    @Column(nullable = false) private UUID changedBy;
    @Column(length = 500) private String note;
    @Column(nullable = false) private Instant createdAt;

    protected TicketHistory() {}
    public TicketHistory(Ticket ticket, TicketStatus from, TicketStatus to, UUID changedBy, String note) {
        this.ticket = ticket; this.fromStatus = from; this.toStatus = to;
        this.changedBy = changedBy; this.note = note; this.createdAt = Instant.now();
    }
    public UUID getId() { return id; }
    public TicketStatus getFromStatus() { return fromStatus; }
    public TicketStatus getToStatus() { return toStatus; }
    public UUID getChangedBy() { return changedBy; }
    public String getNote() { return note; }
    public Instant getCreatedAt() { return createdAt; }
}
