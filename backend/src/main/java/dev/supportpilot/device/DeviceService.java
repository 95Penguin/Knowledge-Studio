package dev.supportpilot.device;

import dev.supportpilot.audit.AuditService;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class DeviceService {
    private final UserDeviceRepository ownerships;
    private final AuditService audit;
    public DeviceService(UserDeviceRepository ownerships, AuditService audit) {
        this.ownerships = ownerships; this.audit = audit;
    }

    public List<DeviceView> list(UUID userId) {
        return ownerships.findAllByUser_Id(userId).stream()
                .map(link -> toView(link.getDevice())).toList();
    }

    public Device requireOwned(UUID userId, UUID deviceId) {
        return ownerships.findByUser_IdAndDevice_Id(userId, deviceId)
                .map(UserDevice::getDevice).orElseThrow(DeviceAccessDeniedException::new);
    }

    public DeviceView get(UUID userId, UUID deviceId, String requestId) {
        long started = System.nanoTime();
        try {
            DeviceView result = toView(requireOwned(userId, deviceId));
            audit.record(userId, requestId, "query_device", "{\"device_id\":\"" + deviceId + "\"}",
                    "SUCCESS", elapsed(started), null);
            return result;
        } catch (RuntimeException error) {
            audit.record(userId, requestId, "query_device", "{\"device_id\":\"" + deviceId + "\"}",
                    "DENIED", elapsed(started), error.getMessage());
            throw error;
        }
    }

    private DeviceView toView(Device device) {
        return new DeviceView(device.getId(), maskSerial(device.getSerialNumber()), device.getName(),
                device.getStatus(), maskIp(device.getInternalIp()), device.getLastSeenAt());
    }

    private String maskSerial(String value) {
        return value.length() <= 4 ? "****" : "****" + value.substring(value.length() - 4);
    }
    private String maskIp(String value) {
        String[] parts = value.split("\\.");
        return parts.length == 4 ? parts[0] + ".***.***." + parts[3] : "***";
    }
    private long elapsed(long started) { return (System.nanoTime() - started) / 1_000_000; }

    public record DeviceView(UUID id, String serialNumber, String name, String status,
                             String internalIp, java.time.Instant lastSeenAt) {}
}
