package dev.supportpilot.ticket;

import dev.supportpilot.auth.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tickets")
public class TicketController {
    private final AuthService auth; private final TicketService tickets;
    public TicketController(AuthService auth, TicketService tickets) { this.auth = auth; this.tickets = tickets; }

    @PostMapping
    public TicketService.TicketView create(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId,
            @Valid @RequestBody CreateTicketRequest request) {
        String safeRequestId = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        return tickets.create(auth.requireUser(token), new TicketService.CreateCommand(
                request.idempotencyKey(), request.deviceId(), request.title(), request.description(),
                request.priority(), request.confirmed()), safeRequestId);
    }
    @GetMapping
    public List<TicketService.TicketView> list(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token) {
        return tickets.list(auth.requireUser(token));
    }
    @GetMapping("/{id}")
    public TicketService.TicketDetailView get(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                                              @PathVariable UUID id) {
        return tickets.get(auth.requireUser(token), id);
    }
    @PatchMapping("/{id}/status")
    public TicketService.TicketView transition(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                                               @PathVariable UUID id,
                                               @Valid @RequestBody TransitionRequest request) {
        return tickets.transition(auth.requireUser(token), id, request.status(), request.note());
    }

    public record CreateTicketRequest(
            @NotBlank @Size(max = 100) String idempotencyKey,
            @NotNull UUID deviceId,
            @NotBlank @Size(max = 120) String title,
            @NotBlank @Size(max = 4000) String description,
            @NotNull TicketPriority priority,
            boolean confirmed) {}
    public record TransitionRequest(@NotNull TicketStatus status, @Size(max = 500) String note) {}
}
