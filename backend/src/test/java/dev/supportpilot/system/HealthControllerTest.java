package dev.supportpilot.system;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;

class HealthControllerTest {
    @Test
    void returnsServiceHealth() {
        Map<String, String> response = new HealthController().health();

        assertThat(response)
                .containsEntry("status", "ok")
                .containsEntry("service", "backend");
    }
}
