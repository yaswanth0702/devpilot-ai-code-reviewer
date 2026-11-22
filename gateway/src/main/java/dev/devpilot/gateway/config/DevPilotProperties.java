package dev.devpilot.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "devpilot")
public record DevPilotProperties(
        String webhookSecret,
        String githubToken,
        String githubApiUrl,
        String agentUrl,
        int maxAttempts,
        long retryBackoffSeconds,
        int agentTimeoutSeconds) {
}
