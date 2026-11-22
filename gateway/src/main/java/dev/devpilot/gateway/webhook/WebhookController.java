package dev.devpilot.gateway.webhook;

import java.util.Map;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import dev.devpilot.gateway.review.ReviewJob;
import dev.devpilot.gateway.review.ReviewJobRepository;

/**
 * GitHub webhook endpoint. It only validates and enqueues; reviews take ~30-90s, longer than
 * GitHub's 10s webhook timeout, so the work happens asynchronously in ReviewWorker.
 */
@RestController
public class WebhookController {

    private static final Logger log = LoggerFactory.getLogger(WebhookController.class);
    private static final Set<String> REVIEW_ACTIONS = Set.of("opened", "synchronize", "reopened", "ready_for_review");

    private final SignatureVerifier verifier;
    private final ReviewJobRepository jobs;
    private final ObjectMapper mapper;

    public WebhookController(SignatureVerifier verifier, ReviewJobRepository jobs, ObjectMapper mapper) {
        this.verifier = verifier;
        this.jobs = jobs;
        this.mapper = mapper;
    }

    @PostMapping("/webhooks/github")
    @Transactional
    public ResponseEntity<Map<String, Object>> receive(
            @RequestHeader(value = "X-Hub-Signature-256", required = false) String signature,
            @RequestHeader(value = "X-GitHub-Event", defaultValue = "") String event,
            @RequestHeader(value = "X-GitHub-Delivery", defaultValue = "") String deliveryId,
            @RequestBody byte[] body) throws Exception {

        if (!verifier.isValid(body, signature)) {
            log.warn("rejected webhook with bad signature delivery={}", deliveryId);
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("error", "invalid signature"));
        }
        if ("ping".equals(event)) {
            return ResponseEntity.ok(Map.of("status", "pong"));
        }
        if (!"pull_request".equals(event)) {
            return ResponseEntity.ok(Map.of("status", "ignored", "reason", "event " + event));
        }

        JsonNode payload = mapper.readTree(body);
        String action = payload.path("action").asText();
        JsonNode pr = payload.path("pull_request");
        if (!REVIEW_ACTIONS.contains(action)) {
            return ResponseEntity.ok(Map.of("status", "ignored", "reason", "action " + action));
        }
        if (pr.path("draft").asBoolean(false)) {
            return ResponseEntity.ok(Map.of("status", "ignored", "reason", "draft PR"));
        }
        if (deliveryId.isBlank() || jobs.existsByDeliveryId(deliveryId)) {
            return ResponseEntity.ok(Map.of("status", "duplicate"));
        }

        JsonNode repo = payload.path("repository");
        ReviewJob job = jobs.save(new ReviewJob(
                deliveryId,
                repo.path("owner").path("login").asText(),
                repo.path("name").asText(),
                pr.path("number").asInt(),
                pr.path("head").path("sha").asText()));
        int superseded = jobs.supersedeOlder(job.getOwner(), job.getRepo(), job.getPrNumber(), job.getId());
        log.info("queued review job={} {}/{}#{} sha={} superseded={}", job.getId(), job.getOwner(),
                job.getRepo(), job.getPrNumber(), job.getHeadSha(), superseded);
        return ResponseEntity.accepted().body(Map.of("status", "queued", "jobId", job.getId()));
    }
}
