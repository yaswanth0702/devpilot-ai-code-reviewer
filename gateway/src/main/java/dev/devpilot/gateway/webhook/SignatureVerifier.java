package dev.devpilot.gateway.webhook;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.springframework.stereotype.Component;

import dev.devpilot.gateway.config.DevPilotProperties;

/** Verifies GitHub's X-Hub-Signature-256 header (HMAC-SHA256 of the raw body). */
@Component
public class SignatureVerifier {

    private final byte[] secret;

    public SignatureVerifier(DevPilotProperties props) {
        if (props.webhookSecret() == null || props.webhookSecret().isBlank()) {
            throw new IllegalStateException("devpilot.webhook-secret must be set");
        }
        this.secret = props.webhookSecret().getBytes(StandardCharsets.UTF_8);
    }

    public boolean isValid(byte[] body, String signatureHeader) {
        if (signatureHeader == null || !signatureHeader.startsWith("sha256=")) {
            return false;
        }
        byte[] expected = sign(body);
        byte[] given;
        try {
            given = HexFormat.of().parseHex(signatureHeader.substring(7));
        } catch (IllegalArgumentException e) {
            return false;
        }
        return MessageDigest.isEqual(expected, given); // constant-time compare
    }

    public byte[] sign(byte[] body) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            return mac.doFinal(body);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
