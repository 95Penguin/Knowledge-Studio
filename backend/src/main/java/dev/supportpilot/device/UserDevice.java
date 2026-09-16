package dev.supportpilot.device;

import dev.supportpilot.user.AppUser;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.util.UUID;

@Entity
@Table(name = "user_device", uniqueConstraints = @UniqueConstraint(columnNames = {"user_id", "device_id"}))
public class UserDevice {
    @Id @GeneratedValue private UUID id;
    @ManyToOne(optional = false) @JoinColumn(name = "user_id") private AppUser user;
    @ManyToOne(optional = false) @JoinColumn(name = "device_id") private Device device;

    protected UserDevice() {}
    public UserDevice(AppUser user, Device device) { this.user = user; this.device = device; }
    public Device getDevice() { return device; }
}
