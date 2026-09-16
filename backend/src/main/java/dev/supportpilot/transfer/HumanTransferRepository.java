package dev.supportpilot.transfer;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface HumanTransferRepository extends JpaRepository<HumanTransfer, UUID> {
    Optional<HumanTransfer> findByUserIdAndConversationId(UUID userId, String conversationId);
}
