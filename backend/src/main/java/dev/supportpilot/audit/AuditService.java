package dev.supportpilot.audit;

import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuditService {
    private final ToolAuditLogRepository logs;
    public AuditService(ToolAuditLogRepository logs) { this.logs = logs; }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(UUID userId, String requestId, String tool, String safeParameters,
                       String result, long durationMs, String error) {
        logs.save(new ToolAuditLog(userId, requestId, tool, safeParameters, result, durationMs, error));
    }
}
