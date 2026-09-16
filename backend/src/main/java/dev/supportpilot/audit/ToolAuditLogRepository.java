package dev.supportpilot.audit;

import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ToolAuditLogRepository extends JpaRepository<ToolAuditLog, UUID> {}
