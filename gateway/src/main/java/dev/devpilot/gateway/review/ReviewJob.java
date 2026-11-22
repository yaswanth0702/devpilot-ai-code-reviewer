package dev.devpilot.gateway.review;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

@Entity
@Table(name = "review_job", indexes = {
        @Index(name = "idx_status_next", columnList = "status,nextAttemptAt"),
        @Index(name = "idx_pr", columnList = "owner,repo,prNumber")})
public class ReviewJob {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String deliveryId; // X-GitHub-Delivery: makes webhook handling idempotent

    @Column(nullable = false) private String owner;
    @Column(nullable = false) private String repo;
    @Column(nullable = false) private int prNumber;
    @Column(nullable = false) private String headSha;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ReviewStatus status = ReviewStatus.QUEUED;

    private int attempts;
    private Instant nextAttemptAt = Instant.now();
    private Instant createdAt = Instant.now();
    private Instant finishedAt;
    private Integer commentsPosted;
    private Integer commentsFiltered;
    private Long durationMs;

    @Column(length = 2000)
    private String lastError;

    @Version
    private long version; // optimistic lock: two workers can't claim the same job

    protected ReviewJob() {
    }

    public ReviewJob(String deliveryId, String owner, String repo, int prNumber, String headSha) {
        this.deliveryId = deliveryId;
        this.owner = owner;
        this.repo = repo;
        this.prNumber = prNumber;
        this.headSha = headSha;
    }

    public Long getId() { return id; }
    public String getDeliveryId() { return deliveryId; }
    public String getOwner() { return owner; }
    public String getRepo() { return repo; }
    public int getPrNumber() { return prNumber; }
    public String getHeadSha() { return headSha; }
    public ReviewStatus getStatus() { return status; }
    public void setStatus(ReviewStatus status) { this.status = status; }
    public int getAttempts() { return attempts; }
    public void setAttempts(int attempts) { this.attempts = attempts; }
    public Instant getNextAttemptAt() { return nextAttemptAt; }
    public void setNextAttemptAt(Instant nextAttemptAt) { this.nextAttemptAt = nextAttemptAt; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getFinishedAt() { return finishedAt; }
    public void setFinishedAt(Instant finishedAt) { this.finishedAt = finishedAt; }
    public Integer getCommentsPosted() { return commentsPosted; }
    public void setCommentsPosted(Integer commentsPosted) { this.commentsPosted = commentsPosted; }
    public Integer getCommentsFiltered() { return commentsFiltered; }
    public void setCommentsFiltered(Integer commentsFiltered) { this.commentsFiltered = commentsFiltered; }
    public Long getDurationMs() { return durationMs; }
    public void setDurationMs(Long durationMs) { this.durationMs = durationMs; }
    public String getLastError() { return lastError; }
    public void setLastError(String lastError) {
        this.lastError = lastError == null ? null : lastError.substring(0, Math.min(lastError.length(), 2000));
    }
}
