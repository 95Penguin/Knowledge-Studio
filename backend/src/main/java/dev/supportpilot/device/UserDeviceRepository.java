package dev.supportpilot.device;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserDeviceRepository extends JpaRepository<UserDevice, UUID> {
    boolean existsByUser_IdAndDevice_Id(UUID userId, UUID deviceId);
    Optional<UserDevice> findByUser_IdAndDevice_Id(UUID userId, UUID deviceId);
    List<UserDevice> findAllByUser_Id(UUID userId);
}
