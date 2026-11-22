package dev.devpilot.gateway.review;

import java.util.List;

import org.springframework.data.domain.PageRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Read-only API to inspect review jobs (status, retries, timings). */
@RestController
@RequestMapping("/api/reviews")
public class ReviewController {

    private final ReviewJobRepository jobs;

    public ReviewController(ReviewJobRepository jobs) {
        this.jobs = jobs;
    }

    @GetMapping
    public List<ReviewJob> recent(@RequestParam(defaultValue = "20") int limit) {
        return jobs.findAllByOrderByCreatedAtDesc(PageRequest.of(0, Math.min(Math.max(limit, 1), 100)));
    }

    @GetMapping("/{id}")
    public ResponseEntity<ReviewJob> one(@PathVariable Long id) {
        return jobs.findById(id).map(ResponseEntity::ok).orElse(ResponseEntity.notFound().build());
    }
}
