package dev.devpilot.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import dev.devpilot.gateway.client.AgentClient;
import dev.devpilot.gateway.client.AgentReview;
import dev.devpilot.gateway.client.GitHubClient;
import dev.devpilot.gateway.review.ReviewJob;
import dev.devpilot.gateway.review.ReviewJobRepository;
import dev.devpilot.gateway.review.ReviewStatus;
import dev.devpilot.gateway.review.ReviewWorker;
import dev.devpilot.gateway.webhook.SignatureVerifier;

@SpringBootTest(properties = {
        "devpilot.webhook-secret=test-secret",
        "devpilot.poll-interval-ms=3600000",   // drive the worker manually in tests
        "devpilot.retry-backoff-seconds=0"})
@AutoConfigureMockMvc
class WebhookAndWorkerIntegrationTest {

    @Autowired MockMvc mvc;
    @Autowired SignatureVerifier signer;
    @Autowired ReviewJobRepository jobs;
    @Autowired ReviewWorker worker;
    @MockitoBean AgentClient agent;
    @MockitoBean GitHubClient github;

    @BeforeEach
    void clean() {
        jobs.deleteAll();
    }

    private String payload(String action, int pr, String sha, boolean draft) {
        return """
            {"action":"%s","pull_request":{"number":%d,"draft":%s,"head":{"sha":"%s"}},
             "repository":{"name":"demo","owner":{"login":"yaswanth0702"}}}""".formatted(action, pr, draft, sha);
    }

    private org.springframework.test.web.servlet.ResultActions send(String event, String delivery, String body, boolean signed)
            throws Exception {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        String sig = signed ? "sha256=" + HexFormat.of().formatHex(signer.sign(bytes)) : "sha256=00";
        return mvc.perform(post("/webhooks/github").contentType(MediaType.APPLICATION_JSON)
                .header("X-GitHub-Event", event).header("X-GitHub-Delivery", delivery)
                .header("X-Hub-Signature-256", sig).content(bytes));
    }

    @Test
    void rejectsBadSignature() throws Exception {
        send("pull_request", "d0", payload("opened", 1, "abc", false), false).andExpect(status().isUnauthorized());
        assertThat(jobs.count()).isZero();
    }

    @Test
    void queuesOpenedPrAndIgnoresNoise() throws Exception {
        send("ping", "p1", "{}", true).andExpect(jsonPath("$.status").value("pong"));
        send("pull_request", "d1", payload("closed", 1, "a", false), true).andExpect(jsonPath("$.status").value("ignored"));
        send("pull_request", "d2", payload("opened", 1, "a", true), true).andExpect(jsonPath("$.reason").value("draft PR"));
        send("pull_request", "d3", payload("opened", 1, "a", false), true).andExpect(status().isAccepted());
        send("pull_request", "d3", payload("opened", 1, "a", false), true).andExpect(jsonPath("$.status").value("duplicate"));
        assertThat(jobs.count()).isEqualTo(1);
    }

    @Test
    void newPushSupersedesQueuedReviewOfOldCommit() throws Exception {
        send("pull_request", "s1", payload("opened", 7, "old", false), true);
        send("pull_request", "s2", payload("synchronize", 7, "new", false), true);
        List<ReviewJob> all = jobs.findAll();
        assertThat(all).extracting(ReviewJob::getHeadSha, ReviewJob::getStatus)
                .containsExactlyInAnyOrder(
                        org.assertj.core.groups.Tuple.tuple("old", ReviewStatus.SUPERSEDED),
                        org.assertj.core.groups.Tuple.tuple("new", ReviewStatus.QUEUED));
    }

    @Test
    void workerReviewsAndPostsToGitHub() throws Exception {
        var review = new AgentReview("Looks risky.", List.of(new AgentReview.Comment(
                "src/A.java", 12, "major", "bug", "NPE when user missing", "null check", 0.9)),
                List.of(new Object()), 3, 3, 1000, 200);
        when(agent.review("yaswanth0702", "demo", 9)).thenReturn(review);

        send("pull_request", "w1", payload("opened", 9, "sha9", false), true);
        worker.poll();

        ReviewJob job = jobs.findAll().get(0);
        assertThat(job.getStatus()).isEqualTo(ReviewStatus.DONE);
        assertThat(job.getCommentsPosted()).isEqualTo(1);
        assertThat(job.getCommentsFiltered()).isEqualTo(1);
        verify(github).postReview("yaswanth0702", "demo", 9, "sha9", review);
    }

    @Test
    void retriesThenFailsPermanently() throws Exception {
        when(agent.review(anyString(), anyString(), anyInt())).thenThrow(new IllegalStateException("agent down"));
        send("pull_request", "f1", payload("opened", 5, "s", false), true);

        for (int i = 0; i < 5; i++) {
            worker.poll();
        }
        ReviewJob job = jobs.findAll().get(0);
        assertThat(job.getStatus()).isEqualTo(ReviewStatus.FAILED);
        assertThat(job.getAttempts()).isEqualTo(3);
        assertThat(job.getLastError()).contains("agent down");
        verify(github, never()).postReview(anyString(), anyString(), anyInt(), anyString(), any());
    }

    @Test
    void reviewApiListsJobs() throws Exception {
        send("pull_request", "a1", payload("opened", 3, "x", false), true);
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/reviews"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].prNumber").value(3))
                .andExpect(jsonPath("$[0].status").value("QUEUED"));
    }
}
