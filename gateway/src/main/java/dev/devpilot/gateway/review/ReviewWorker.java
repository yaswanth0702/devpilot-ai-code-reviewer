package dev.devpilot.gateway.review;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import dev.devpilot.gateway.client.AgentClient;
import dev.devpilot.gateway.client.AgentReview;
import dev.devpilot.gateway.client.GitHubClient;
import dev.devpilot.gateway.config.DevPilotProperties;

/**
 * Polls the database for queued jobs. Using the DB as the queue means jobs survive restarts and
 * several gateway instances can run safely (optimistic locking decides who claims a job).
 */
@Component
public class ReviewWorker {

    private static final Logger log = LoggerFactory.getLogger(ReviewWorker.class);

    private final ReviewJobRepository jobs;
    private final AgentClient agent;
    private final GitHubClient github;
    private final DevPilotProperties props;

    public ReviewWorker(ReviewJobRepository jobs, AgentClient agent, GitHubClient github, DevPilotProperties props) {
        this.jobs = jobs;
        this.agent = agent;
        this.github = github;
        this.props = props;
    }

    @Scheduled(fixedDelayString = "${devpilot.poll-interval-ms:2000}")
    public void poll() {
        List<ReviewJob> due = jobs.findByStatusAndNextAttemptAtBeforeOrderByCreatedAtAsc(
                ReviewStatus.QUEUED, Instant.now().plusMillis(1), PageRequest.of(0, 5));
        for (ReviewJob job : due) {
            ReviewJob claimed = claim(job);
            if (claimed != null) {
                process(claimed);
            }
        }
    }

    private ReviewJob claim(ReviewJob job) {
        try {
            job.setStatus(ReviewStatus.RUNNING);
            job.setAttempts(job.getAttempts() + 1);
            return jobs.saveAndFlush(job);
        } catch (ObjectOptimisticLockingFailureException e) {
            return null; // another worker got it
        }
    }

    void process(ReviewJob job) {
        long start = System.nanoTime();
        try {
            AgentReview review = agent.review(job.getOwner(), job.getRepo(), job.getPrNumber());
            github.postReview(job.getOwner(), job.getRepo(), job.getPrNumber(), job.getHeadSha(), review);
            job.setStatus(ReviewStatus.DONE);
            job.setCommentsPosted(review.comments().size());
            job.setCommentsFiltered(review.droppedCount());
            job.setLastError(null);
            job.setFinishedAt(Instant.now());
            log.info("review done job={} comments={} filtered={}", job.getId(),
                    review.comments().size(), review.droppedCount());
        } catch (Exception e) {
            job.setLastError(e.getClass().getSimpleName() + ": " + e.getMessage());
            if (job.getAttempts() >= props.maxAttempts()) {
                job.setStatus(ReviewStatus.FAILED);
                job.setFinishedAt(Instant.now());
                log.error("review failed permanently job={} attempts={}", job.getId(), job.getAttempts(), e);
            } else {
                long backoff = props.retryBackoffSeconds() * (1L << (job.getAttempts() - 1)); // exponential
                job.setStatus(ReviewStatus.QUEUED);
                job.setNextAttemptAt(Instant.now().plus(Duration.ofSeconds(backoff)));
                log.warn("review attempt {} failed job={}, retrying in {}s: {}", job.getAttempts(), job.getId(),
                        backoff, e.getMessage());
            }
        } finally {
            job.setDurationMs((System.nanoTime() - start) / 1_000_000);
            jobs.save(job);
        }
    }
}
