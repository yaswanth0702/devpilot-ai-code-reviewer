package dev.devpilot.gateway.client;

import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.ObjectMapper;

@Component
public class AgentClient {

    private final RestClient http;
    private final ObjectMapper snake = new ObjectMapper()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

    public AgentClient(RestClient agentRestClient) {
        this.http = agentRestClient;
    }

    public AgentReview review(String owner, String repo, int prNumber) {
        String json = http.post().uri("/review")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("owner", owner, "repo", repo, "pr_number", prNumber))
                .retrieve()
                .body(String.class);
        try {
            return snake.readValue(json, AgentReview.class);
        } catch (Exception e) {
            throw new IllegalStateException("bad agent response: " + e.getMessage(), e);
        }
    }
}
