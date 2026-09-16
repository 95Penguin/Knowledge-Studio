package dev.supportpilot.auth;

import dev.supportpilot.user.AppUser;
import dev.supportpilot.user.UserRepository;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
    private final UserRepository users;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();

    public AuthService(UserRepository users) { this.users = users; }

    public LoginResult login(String email, String password) {
        AppUser user = users.findByEmailIgnoreCase(email)
                .filter(candidate -> passwordEncoder.matches(password, candidate.getPasswordHash()))
                .orElseThrow(() -> new UnauthorizedException("邮箱或密码错误"));
        String token = UUID.randomUUID().toString() + UUID.randomUUID();
        Instant expiresAt = Instant.now().plus(12, ChronoUnit.HOURS);
        sessions.put(token, new Session(user.getId(), expiresAt));
        return new LoginResult(token, expiresAt, user.getId(), user.getDisplayName());
    }

    public UUID requireUser(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw new UnauthorizedException("缺少 Bearer 登录令牌");
        }
        String token = authorization.substring(7).trim();
        Session session = sessions.get(token);
        if (session == null || session.expiresAt().isBefore(Instant.now())) {
            sessions.remove(token);
            throw new UnauthorizedException("登录令牌无效或已过期");
        }
        return session.userId();
    }

    public String encodePassword(String password) { return passwordEncoder.encode(password); }

    private record Session(UUID userId, Instant expiresAt) {}
    public record LoginResult(String accessToken, Instant expiresAt, UUID userId, String displayName) {}
}
