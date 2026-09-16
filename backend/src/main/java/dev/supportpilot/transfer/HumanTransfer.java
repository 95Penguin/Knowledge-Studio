package dev.supportpilot.transfer;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "human_transfer")
public class HumanTransfer {
    @Id @GeneratedValue private UUID id;
    @Column(nullable = false) private UUID userId;
    @Column(nullable = false, unique = true) private String conversationId;
    @Column(nullable = false, length = 500) private String reason;
    @Column(nullable = false, length = 4000) private String summary;
    @Column(nullable = false) private String status;
    @Column(nullable = false) private Instant createdAt;

    protected HumanTransfer() {}
    public HumanTransfer(UUID userId, String conversationId, String reason, String summary) {
        this.userId = userId; this.conversationId = conversationId; this.reason = reason;
        this.summary = summary; this.status = "PENDING"; this.createdAt = Instant.now();
    }
    public UUID getId() { return id; }
    public String getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
}
