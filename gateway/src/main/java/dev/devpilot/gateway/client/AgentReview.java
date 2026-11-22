package dev.devpilot.gateway.client;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Response from the Python agent service's POST /review. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record AgentReview(String summary, List<Comment> comments, List<Object> dropped,
                          int steps, int toolCalls, int inputTokens, int outputTokens) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Comment(String path, int line, String severity, String category,
                          String body, String suggestion, double confidence) {
    }

    public int droppedCount() {
        return dropped == null ? 0 : dropped.size();
    }
}
