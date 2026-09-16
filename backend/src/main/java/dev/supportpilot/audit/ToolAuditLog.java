package dev.supportpilot.audit;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "tool_audit_log")
public class ToolAuditLog {
    @Id @GeneratedValue private UUID id;
    @Column(nullable = false) private UUID userId;
    @Column(nullable = false) private String requestId;
    @Column(nullable = false) private String toolName;
    @Column(nullable = false, length = 2000) private String parametersJson;
    @Column(nullable = false) private String resultStatus;
    @Column(nullable = false) private long durationMs;
    @Column(length = 1000) private String errorMessage;
    @Column(nullable = false) private Instant createdAt;

    protected ToolAuditLog() {}
    public ToolAuditLog(UUID userId, String requestId, String toolName, String parametersJson,
                        String resultStatus, long durationMs, String errorMessage) {
        this.userId = userId; this.requestId = requestId; this.toolName = toolName;
        this.parametersJson = parametersJson; this.resultStatus = resultStatus;
        this.durationMs = durationMs; this.errorMessage = errorMessage; this.createdAt = Instant.now();
    }
}
