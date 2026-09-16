package dev.supportpilot.device;

import dev.supportpilot.auth.AuthService;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/devices")
public class DeviceController {
    private final AuthService auth; private final DeviceService devices;
    public DeviceController(AuthService auth, DeviceService devices) { this.auth = auth; this.devices = devices; }

    @GetMapping
    public List<DeviceService.DeviceView> list(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token) {
        return devices.list(auth.requireUser(token));
    }
    @GetMapping("/{id}")
    public DeviceService.DeviceView get(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                                        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
                                        @PathVariable UUID id) {
        String safeRequestId = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
        return devices.get(auth.requireUser(token), id, safeRequestId);
    }
}
