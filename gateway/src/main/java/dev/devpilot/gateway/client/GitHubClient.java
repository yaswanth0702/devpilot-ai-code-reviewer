package dev.devpilot.gateway.client;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/** Posts the agent's review to the PR as one GitHub review with inline comments. */
@Component
public class GitHubClient {

    private final RestClient http;

    public GitHubClient(RestClient githubRestClient) {
        this.http = githubRestClient;
    }

    public void postReview(String owner, String repo, int prNumber, String headSha, AgentReview review) {
        List<Map<String, Object>> comments = new ArrayList<>();
        for (AgentReview.Comment c : review.comments()) {
            comments.add(Map.of("path", c.path(), "line", c.line(), "side", "RIGHT", "body", formatComment(c)));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("commit_id", headSha); // pin to the reviewed commit so line numbers stay correct
        body.put("event", "COMMENT");   // never auto-approve or block: a human stays in charge
        body.put("body", formatSummary(review));
        body.put("comments", comments);

        http.post().uri("/repos/{o}/{r}/pulls/{n}/reviews", owner, repo, prNumber)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .toBodilessEntity();
    }

    static String formatComment(AgentReview.Comment c) {
        StringBuilder sb = new StringBuilder()
                .append("**").append(c.severity().toUpperCase()).append("** · ").append(c.category())
                .append("\n\n").append(c.body());
        if (c.suggestion() != null && !c.suggestion().isBlank()) {
            sb.append("\n\n**Suggested fix:** ").append(c.suggestion());
        }
        return sb.append("\n\n<sub>DevPilot · confidence ")
                .append(String.format("%.2f", c.confidence())).append("</sub>").toString();
    }

    static String formatSummary(AgentReview r) {
        return "### 🤖 DevPilot review\n\n" + r.summary()
                + "\n\n<sub>" + r.comments().size() + " comment(s) posted · "
                + r.droppedCount() + " filtered by verifier · " + r.toolCalls() + " tool calls</sub>";
    }
}
