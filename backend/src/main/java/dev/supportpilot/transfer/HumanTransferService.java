package dev.supportpilot.transfer;

import dev.supportpilot.audit.AuditService;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class HumanTransferService {
    private final HumanTransferRepository transfers; private final AuditService audit;
    public HumanTransferService(HumanTransferRepository transfers, AuditService audit) {
        this.transfers = transfers; this.audit = audit;
    }
    @Transactional
    public TransferView create(UUID userId, String conversationId, String reason,
                               String summary, String requestId) {
        var existing = transfers.findByUserIdAndConversationId(userId, conversationId);
        if (existing.isPresent()) return view(existing.get(), true);
        HumanTransfer transfer = transfers.save(new HumanTransfer(userId, conversationId, reason, summary));
        audit.record(userId, requestId, "transfer_to_human", "{\"conversation_id\":\"" + conversationId + "\"}",
                "SUCCESS", 0, null);
        return view(transfer, false);
    }
    private TransferView view(HumanTransfer transfer, boolean replayed) {
        return new TransferView(transfer.getId(), transfer.getStatus(), transfer.getCreatedAt(), replayed);
    }
    public record TransferView(UUID id, String status, java.time.Instant createdAt, boolean idempotencyReplay) {}
}
