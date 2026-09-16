package dev.supportpilot.transfer;

import dev.supportpilot.auth.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/transfers")
public class HumanTransferController {
    private final AuthService auth; private final HumanTransferService transfers;
    public HumanTransferController(AuthService auth, HumanTransferService transfers) {
        this.auth = auth; this.transfers = transfers;
    }
    @PostMapping
    public HumanTransferService.TransferView create(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId,
            @Valid @RequestBody TransferRequest request) {
        String rid = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        return transfers.create(auth.requireUser(token), request.conversationId(), request.reason(), request.summary(), rid);
    }
    public record TransferRequest(@NotBlank String conversationId,
                                  @NotBlank @Size(max = 500) String reason,
                                  @NotBlank @Size(max = 4000) String summary) {}
}
