package dev.supportpilot.system;

import dev.supportpilot.auth.UnauthorizedException;
import dev.supportpilot.device.DeviceAccessDeniedException;
import dev.supportpilot.ticket.IllegalTicketTransitionException;
import java.time.Instant;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(UnauthorizedException.class)
    ResponseEntity<Map<String, Object>> unauthorized(UnauthorizedException error) {
        return response(HttpStatus.UNAUTHORIZED, error.getMessage());
    }
    @ExceptionHandler(DeviceAccessDeniedException.class)
    ResponseEntity<Map<String, Object>> forbidden(DeviceAccessDeniedException error) {
        return response(HttpStatus.FORBIDDEN, error.getMessage());
    }
    @ExceptionHandler({IllegalArgumentException.class, IllegalTicketTransitionException.class,
            MethodArgumentNotValidException.class})
    ResponseEntity<Map<String, Object>> badRequest(Exception error) {
        return response(HttpStatus.BAD_REQUEST, error.getMessage());
    }
    private ResponseEntity<Map<String, Object>> response(HttpStatus status, String message) {
        return ResponseEntity.status(status).body(Map.of(
                "status", status.value(), "error", status.getReasonPhrase(),
                "message", message, "timestamp", Instant.now().toString()));
    }
}
