package dev.devpilot.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.util.HexFormat;

import org.junit.jupiter.api.Test;

import dev.devpilot.gateway.config.DevPilotProperties;
import dev.devpilot.gateway.webhook.SignatureVerifier;

class SignatureVerifierTest {

    private final SignatureVerifier verifier = new SignatureVerifier(
            new DevPilotProperties("It's a Secret to Everybody", "", "", "", 3, 1, 10));

    @Test
    void matchesGitHubDocumentedExample() {
        // Test vector from GitHub's "Validating webhook deliveries" docs
        byte[] body = "Hello, World!".getBytes(StandardCharsets.UTF_8);
        String header = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17";
        assertThat(verifier.isValid(body, header)).isTrue();
    }

    @Test
    void rejectsTamperedBodyMissingAndMalformedHeaders() {
        byte[] body = "Hello, World!".getBytes(StandardCharsets.UTF_8);
        String good = "sha256=" + HexFormat.of().formatHex(verifier.sign(body));
        assertThat(verifier.isValid("Hello, World?".getBytes(StandardCharsets.UTF_8), good)).isFalse();
        assertThat(verifier.isValid(body, null)).isFalse();
        assertThat(verifier.isValid(body, "sha1=abc")).isFalse();
        assertThat(verifier.isValid(body, "sha256=zzzz")).isFalse();
    }
}
