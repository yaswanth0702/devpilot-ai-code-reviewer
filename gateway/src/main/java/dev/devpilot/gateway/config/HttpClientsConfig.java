package dev.devpilot.gateway.config;

import java.net.http.HttpClient;
import java.time.Duration;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class HttpClientsConfig {

    @Bean
    RestClient agentRestClient(DevPilotProperties props) {
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5)).build());
        factory.setReadTimeout(Duration.ofSeconds(props.agentTimeoutSeconds()));
        return RestClient.builder().baseUrl(props.agentUrl()).requestFactory(factory).build();
    }

    @Bean
    RestClient githubRestClient(DevPilotProperties props) {
        return RestClient.builder()
                .baseUrl(props.githubApiUrl())
                .defaultHeader("Accept", "application/vnd.github+json")
                .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
                .defaultHeader("Authorization", "Bearer " + props.githubToken())
                .build();
    }
}
