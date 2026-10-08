package dev.supportpilot.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.supportpilot.auth.AuthService;
import dev.supportpilot.device.DeviceService;
import dev.supportpilot.ticket.TicketPriority;
import dev.supportpilot.ticket.TicketService;
import dev.supportpilot.transfer.HumanTransferService;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** A stateless JSON-RPC MCP endpoint; business authorization remains in Java services. */
@RestController
public class McpController {
    private final AuthService auth;
    private final DeviceService devices;
    private final TicketService tickets;
    private final HumanTransferService transfers;
    private final ObjectMapper mapper;

    public McpController(AuthService auth, DeviceService devices, TicketService tickets,
                         HumanTransferService transfers, ObjectMapper mapper) {
        this.auth = auth; this.devices = devices; this.tickets = tickets;
        this.transfers = transfers; this.mapper = mapper;
    }

    @PostMapping("/mcp")
    public Map<String, Object> handle(
            @RequestBody JsonNode request,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {
        JsonNode id = request.path("id");
        if (!"2.0".equals(request.path("jsonrpc").asText()) || !request.path("method").isTextual()) {
            return error(id, -32600, "Invalid JSON-RPC request");
        }
        String method = request.path("method").asText();
        try {
            Object result = switch (method) {
                case "initialize" -> Map.of(
                        "protocolVersion", "2025-03-26",
                        "capabilities", Map.of("tools", Map.of()),
                        "serverInfo", Map.of("name", "supportpilot-java", "version", "0.1.0"));
                case "tools/list" -> Map.of("tools", tools());
                case "tools/call" -> call(request.path("params"), authorization, requestId);
                default -> null;
            };
            if (result == null) return error(id, -32601, "Method not found");
            return Map.of("jsonrpc", "2.0", "id", id, "result", result);
        } catch (IllegalArgumentException exception) {
            return error(id, -32602, exception.getMessage());
        }
    }

    private Object call(JsonNode params, String authorization, String requestId) {
        String name = required(params, "name");
        JsonNode args = params.path("arguments");
        UUID userId = auth.requireUser(authorization);
        String rid = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        Object value = switch (name) {
            case "current_user" -> Map.of("userId", userId);
            case "query_device" -> devices.get(userId, UUID.fromString(required(args, "deviceId")), rid);
            case "create_ticket" -> tickets.create(userId, new TicketService.CreateCommand(
                    required(args, "idempotencyKey"), UUID.fromString(required(args, "deviceId")),
                    required(args, "title"), required(args, "description"),
                    TicketPriority.valueOf(required(args, "priority")),
                    args.path("confirmed").asBoolean(false)), rid);
            case "transfer_to_human" -> transfers.create(userId, required(args, "conversationId"),
                    required(args, "reason"), required(args, "summary"), rid);
            default -> throw new IllegalArgumentException("Unknown tool: " + name);
        };
        try {
            return Map.of("content", List.of(Map.of("type", "text", "text", mapper.writeValueAsString(value))),
                    "isError", false);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to serialize tool response", exception);
        }
    }

    private String required(JsonNode args, String field) {
        JsonNode value = args.path(field);
        if (!value.isTextual() || value.asText().isBlank()) {
            throw new IllegalArgumentException("Missing or invalid argument: " + field);
        }
        return value.asText();
    }

    private List<Map<String, Object>> tools() {
        return List.of(
                tool("current_user", "Read the authenticated user identity", Map.of()),
                tool("query_device", "Read an owned device after user authorization", Map.of("deviceId", "string")),
                tool("create_ticket", "Create a confirmed, idempotent support ticket", Map.of(
                        "idempotencyKey", "string", "deviceId", "string", "title", "string",
                        "description", "string", "priority", "string", "confirmed", "boolean")),
                tool("transfer_to_human", "Create an audited human transfer", Map.of(
                        "conversationId", "string", "reason", "string", "summary", "string"))
        );
    }

    private Map<String, Object> tool(String name, String description, Map<String, String> fields) {
        Map<String, Object> properties = new java.util.LinkedHashMap<>();
        fields.forEach((field, type) -> properties.put(field, Map.of("type", type)));
        return Map.of("name", name, "description", description, "inputSchema", Map.of(
                "type", "object", "properties", properties, "required", fields.keySet().stream().toList(),
                "additionalProperties", false));
    }

    private Map<String, Object> error(JsonNode id, int code, String message) {
        return Map.of("jsonrpc", "2.0", "id", id,
                "error", Map.of("code", code, "message", message));
    }
}
