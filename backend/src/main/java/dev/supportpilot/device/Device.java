package dev.supportpilot.device;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "device")
public class Device {
    @Id @GeneratedValue private UUID id;
    @Column(nullable = false, unique = true) private String serialNumber;
    @Column(nullable = false) private String name;
    @Column(nullable = false) private String status;
    @Column(nullable = false) private String internalIp;
    @Column(nullable = false) private Instant lastSeenAt;

    protected Device() {}
    public Device(String serialNumber, String name, String status, String internalIp, Instant lastSeenAt) {
        this.serialNumber = serialNumber; this.name = name; this.status = status;
        this.internalIp = internalIp; this.lastSeenAt = lastSeenAt;
    }
    public UUID getId() { return id; }
    public String getSerialNumber() { return serialNumber; }
    public String getName() { return name; }
    public String getStatus() { return status; }
    public String getInternalIp() { return internalIp; }
    public Instant getLastSeenAt() { return lastSeenAt; }
}
