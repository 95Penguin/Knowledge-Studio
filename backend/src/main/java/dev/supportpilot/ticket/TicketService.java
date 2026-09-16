package dev.supportpilot.ticket;

import dev.supportpilot.audit.AuditService;
import dev.supportpilot.device.Device;
import dev.supportpilot.device.DeviceService;
import dev.supportpilot.user.AppUser;
import dev.supportpilot.user.UserRepository;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketService {
    private static final Map<TicketStatus, EnumSet<TicketStatus>> ALLOWED = Map.of(
            TicketStatus.OPEN, EnumSet.of(TicketStatus.IN_PROGRESS),
            TicketStatus.IN_PROGRESS, EnumSet.of(TicketStatus.RESOLVED),
            TicketStatus.RESOLVED, EnumSet.of(TicketStatus.IN_PROGRESS, TicketStatus.CLOSED),
            TicketStatus.CLOSED, EnumSet.noneOf(TicketStatus.class));

    private final TicketRepository tickets;
    private final TicketHistoryRepository history;
    private final UserRepository users;
    private final DeviceService devices;
    private final AuditService audit;

    public TicketService(TicketRepository tickets, TicketHistoryRepository history,
                         UserRepository users, DeviceService devices, AuditService audit) {
        this.tickets = tickets; this.history = history; this.users = users;
        this.devices = devices; this.audit = audit;
    }

    @Transactional
    public TicketView create(UUID userId, CreateCommand command, String requestId) {
        long started = System.nanoTime();
        try {
            var existing = tickets.findByUser_IdAndIdempotencyKey(userId, command.idempotencyKey());
            if (existing.isPresent()) {
                recordCreateAudit(userId, requestId, command, "IDEMPOTENT_REPLAY", started, null);
                return toView(existing.get(), true);
            }
            if (!command.confirmed()) throw new IllegalArgumentException("创建工单前必须获得用户明确确认");

            AppUser user = users.findById(userId).orElseThrow();
            Device device = devices.requireOwned(userId, command.deviceId());
            Ticket ticket = tickets.save(new Ticket(user, device, command.idempotencyKey(),
                    command.title(), command.description(), command.priority()));
            history.save(new TicketHistory(ticket, null, TicketStatus.OPEN, userId, "用户创建工单"));
            recordCreateAudit(userId, requestId, command, "SUCCESS", started, null);
            return toView(ticket, false);
        } catch (RuntimeException error) {
            recordCreateAudit(userId, requestId, command, "FAILED", started, error.getMessage());
            throw error;
        }
    }

    @Transactional(readOnly = true)
    public List<TicketView> list(UUID userId) {
        return tickets.findAllByUser_IdOrderByCreatedAtDesc(userId).stream()
                .map(ticket -> toView(ticket, false)).toList();
    }

    @Transactional(readOnly = true)
    public TicketDetailView get(UUID userId, UUID ticketId) {
        Ticket ticket = requireOwned(userId, ticketId);
        List<HistoryView> timeline = history.findAllByTicket_IdOrderByCreatedAtAsc(ticketId).stream()
                .map(item -> new HistoryView(item.getId(), item.getFromStatus(), item.getToStatus(),
                        item.getChangedBy(), item.getNote(), item.getCreatedAt()))
                .toList();
        return new TicketDetailView(toView(ticket, false), ticket.getDeviceName(), timeline,
                List.copyOf(ALLOWED.get(ticket.getStatus())));
    }

    @Transactional
    public TicketView transition(UUID userId, UUID ticketId, TicketStatus next, String note) {
        Ticket ticket = requireOwned(userId, ticketId);
        TicketStatus previous = ticket.getStatus();
        if (!ALLOWED.get(previous).contains(next)) throw new IllegalTicketTransitionException(previous, next);
        ticket.transitionTo(next);
        history.save(new TicketHistory(ticket, previous, next, userId, note));
        return toView(ticket, false);
    }

    private Ticket requireOwned(UUID userId, UUID ticketId) {
        return tickets.findByIdAndUser_Id(ticketId, userId)
                .orElseThrow(() -> new IllegalArgumentException("工单不存在或当前用户无权访问"));
    }
    private long elapsed(long started) { return (System.nanoTime() - started) / 1_000_000; }
    private void recordCreateAudit(UUID userId, String requestId, CreateCommand command,
                                   String result, long started, String error) {
        audit.record(userId, requestId, "create_ticket",
                "{\"device_id\":\"" + command.deviceId() + "\",\"priority\":\"" + command.priority() + "\"}",
                result, elapsed(started), error);
    }
    private TicketView toView(Ticket ticket, boolean replayed) {
        return new TicketView(ticket.getId(), ticket.getDeviceId(), ticket.getTitle(),
                ticket.getDescription(), ticket.getPriority(), ticket.getStatus(),
                ticket.getCreatedAt(), ticket.getUpdatedAt(), replayed);
    }

    public record CreateCommand(String idempotencyKey, UUID deviceId, String title,
                                String description, TicketPriority priority, boolean confirmed) {}
    public record TicketView(UUID id, UUID deviceId, String title, String description,
                             TicketPriority priority, TicketStatus status,
                             java.time.Instant createdAt, java.time.Instant updatedAt,
                             boolean idempotencyReplay) {}
    public record HistoryView(UUID id, TicketStatus fromStatus, TicketStatus toStatus,
                              UUID changedBy, String note, java.time.Instant createdAt) {}
    public record TicketDetailView(TicketView ticket, String deviceName, List<HistoryView> history,
                                   List<TicketStatus> allowedTransitions) {}
}
