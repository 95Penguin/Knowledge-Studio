package dev.supportpilot;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.supportpilot.audit.ToolAuditLogRepository;
import dev.supportpilot.auth.AuthService;
import dev.supportpilot.device.Device;
import dev.supportpilot.device.DeviceRepository;
import dev.supportpilot.device.UserDevice;
import dev.supportpilot.device.UserDeviceRepository;
import dev.supportpilot.ticket.TicketHistoryRepository;
import dev.supportpilot.ticket.TicketRepository;
import dev.supportpilot.user.AppUser;
import dev.supportpilot.user.UserRepository;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class P0BusinessFlowIntegrationTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired AuthService auth;
    @Autowired UserRepository users;
    @Autowired DeviceRepository devices;
    @Autowired UserDeviceRepository ownerships;
    @Autowired TicketRepository tickets;
    @Autowired TicketHistoryRepository history;
    @Autowired ToolAuditLogRepository audits;

    @Test
    void enforcesIdentityOwnershipIdempotencyStateMachineAndAudit() throws Exception {
        String token = login("demo@supportpilot.dev", "demo1234");
        JsonNode deviceList = json.readTree(mvc.perform(get("/api/devices")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        String deviceId = deviceList.get(0).get("id").asText();

        mvc.perform(get("/api/devices/{id}", deviceId)
                        .header("Authorization", "Bearer " + token)
                        .header("X-Request-Id", "query-owned-device"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.serialNumber").value("****0001"))
                .andExpect(jsonPath("$.internalIp").value("10.***.***.15"));

        AppUser other = users.save(new AppUser("other@example.com", auth.encodePassword("other-pass"), "Other"));
        Device otherDevice = devices.save(new Device("SP-OTHER-9999", "Other Redis", "ONLINE",
                "10.9.1.20", Instant.now()));
        ownerships.save(new UserDevice(other, otherDevice));

        mvc.perform(get("/api/devices/{id}", otherDevice.getId())
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isForbidden());

        String unconfirmed = ticketBody("ticket-key-1", deviceId, false);
        mvc.perform(post("/api/tickets").header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON).content(unconfirmed))
                .andExpect(status().isBadRequest());
        assertThat(tickets.count()).isZero();

        String confirmed = ticketBody("ticket-key-1", deviceId, true);
        JsonNode created = json.readTree(mvc.perform(post("/api/tickets")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Request-Id", "create-ticket-1")
                        .contentType(MediaType.APPLICATION_JSON).content(confirmed))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("OPEN"))
                .andExpect(jsonPath("$.idempotencyReplay").value(false))
                .andReturn().getResponse().getContentAsString());
        String ticketId = created.get("id").asText();

        mvc.perform(post("/api/tickets").header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON).content(confirmed))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(ticketId))
                .andExpect(jsonPath("$.idempotencyReplay").value(true));
        assertThat(tickets.count()).isOne();

        mvc.perform(patch("/api/tickets/{id}/status", ticketId)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"RESOLVED\",\"note\":\"skip\"}"))
                .andExpect(status().isBadRequest());

        mvc.perform(patch("/api/tickets/{id}/status", ticketId)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"IN_PROGRESS\",\"note\":\"accepted\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("IN_PROGRESS"));

        mvc.perform(get("/api/tickets/{id}", ticketId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ticket.id").value(ticketId))
                .andExpect(jsonPath("$.deviceName").value("Redis Primary"))
                .andExpect(jsonPath("$.history.length()").value(2))
                .andExpect(jsonPath("$.allowedTransitions[0]").value("RESOLVED"));

        assertThat(history.count()).isEqualTo(2);
        assertThat(audits.count()).isGreaterThanOrEqualTo(3);
    }

    @Test
    void rejectsMissingTokenAndBadLogin() throws Exception {
        mvc.perform(get("/api/devices")).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"demo@supportpilot.dev\",\"password\":\"wrong\"}"))
                .andExpect(status().isUnauthorized());
    }

    private String login(String email, String password) throws Exception {
        String response = mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(java.util.Map.of("email", email, "password", password))))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        return json.readTree(response).get("accessToken").asText();
    }

    private String ticketBody(String key, String deviceId, boolean confirmed) throws Exception {
        return json.writeValueAsString(java.util.Map.of(
                "idempotencyKey", key, "deviceId", deviceId,
                "title", "Redis latency incident", "description", "Latency remains high after checks",
                "priority", "HIGH", "confirmed", confirmed));
    }
}
