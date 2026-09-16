package dev.supportpilot.ticket;

import dev.supportpilot.device.Device;
import dev.supportpilot.user.AppUser;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "ticket", uniqueConstraints = @UniqueConstraint(columnNames = {"user_id", "idempotency_key"}))
public class Ticket {
    @Id @GeneratedValue private UUID id;
    @ManyToOne(optional = false) @JoinColumn(name = "user_id") private AppUser user;
    @ManyToOne(optional = false) @JoinColumn(name = "device_id") private Device device;
    @Column(name = "idempotency_key", nullable = false, length = 100) private String idempotencyKey;
    @Column(nullable = false, length = 120) private String title;
    @Column(nullable = false, length = 4000) private String description;
    @Enumerated(EnumType.STRING) @Column(nullable = false) private TicketPriority priority;
    @Enumerated(EnumType.STRING) @Column(nullable = false) private TicketStatus status;
    @Column(nullable = false) private Instant createdAt;
    @Column(nullable = false) private Instant updatedAt;
    @Version private long version;

    protected Ticket() {}
    public Ticket(AppUser user, Device device, String key, String title, String description, TicketPriority priority) {
        this.user = user; this.device = device; this.idempotencyKey = key; this.title = title;
        this.description = description; this.priority = priority; this.status = TicketStatus.OPEN;
        this.createdAt = Instant.now(); this.updatedAt = this.createdAt;
    }
    public void transitionTo(TicketStatus next) { this.status = next; this.updatedAt = Instant.now(); }
    public UUID getId() { return id; }
    public UUID getUserId() { return user.getId(); }
    public UUID getDeviceId() { return device.getId(); }
    public String getDeviceName() { return device.getName(); }
    public String getTitle() { return title; }
    public String getDescription() { return description; }
    public TicketPriority getPriority() { return priority; }
    public TicketStatus getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
}
