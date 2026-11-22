package dev.devpilot.gateway.review;

import java.time.Instant;
import java.util.List;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ReviewJobRepository extends JpaRepository<ReviewJob, Long> {

    boolean existsByDeliveryId(String deliveryId);

    List<ReviewJob> findByStatusAndNextAttemptAtBeforeOrderByCreatedAtAsc(
            ReviewStatus status, Instant now, Pageable page);

    List<ReviewJob> findAllByOrderByCreatedAtDesc(Pageable page);

    /** A newer push to the same PR makes older queued reviews pointless. */
    @Modifying
    @Query("""
            update ReviewJob j set j.status = dev.devpilot.gateway.review.ReviewStatus.SUPERSEDED
            where j.owner = :owner and j.repo = :repo and j.prNumber = :pr
              and j.status = dev.devpilot.gateway.review.ReviewStatus.QUEUED and j.id <> :keepId""")
    int supersedeOlder(@Param("owner") String owner, @Param("repo") String repo,
                       @Param("pr") int pr, @Param("keepId") Long keepId);
}
