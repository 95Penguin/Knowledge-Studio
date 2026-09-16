package dev.supportpilot.system;

import dev.supportpilot.auth.AuthService;
import dev.supportpilot.device.Device;
import dev.supportpilot.device.DeviceRepository;
import dev.supportpilot.device.UserDevice;
import dev.supportpilot.device.UserDeviceRepository;
import dev.supportpilot.user.AppUser;
import dev.supportpilot.user.UserRepository;
import java.time.Instant;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class DemoDataInitializer implements CommandLineRunner {
    private final UserRepository users; private final DeviceRepository devices;
    private final UserDeviceRepository ownerships; private final AuthService auth;
    public DemoDataInitializer(UserRepository users, DeviceRepository devices,
                               UserDeviceRepository ownerships, AuthService auth) {
        this.users = users; this.devices = devices; this.ownerships = ownerships; this.auth = auth;
    }

    @Override @Transactional
    public void run(String... args) {
        if (users.findByEmailIgnoreCase("demo@supportpilot.dev").isPresent()) return;
        AppUser user = users.save(new AppUser("demo@supportpilot.dev",
                auth.encodePassword("demo1234"), "Demo User"));
        Device device = devices.save(new Device("SP-REDIS-0001", "Redis Primary",
                "DEGRADED", "10.20.8.15", Instant.now()));
        ownerships.save(new UserDevice(user, device));
    }
}
