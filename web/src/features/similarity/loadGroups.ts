import { getJson, similarityGroupsUrl } from "../../api";
import type { LatestRequestGuard } from "../../requestGuard";
import type { SimilarityAgeFilter, SimilarityConfidenceFilter, SimilarityGroupsResponse, SimilarityReviewFilter } from "./types";

type GroupQuery = {
  limit: number;
  offset: number;
  reviewFilter: SimilarityReviewFilter;
  albumId: string;
  confidenceFilter: SimilarityConfidenceFilter;
  ageFilter: SimilarityAgeFilter;
};

/** One request path for navigation and invalidation after saving a review. */
export function loadGroups(query: GroupQuery, guard: LatestRequestGuard,
  apply: (groups: SimilarityGroupsResponse) => void, fail: (message: string) => void) {
  const controller = new AbortController();
  const token = guard.begin();
  const url = similarityGroupsUrl(query.limit, query.offset, query.reviewFilter,
    query.albumId, query.confidenceFilter, query.ageFilter);
  void getJson<SimilarityGroupsResponse>(url, { signal: controller.signal })
    .then((result) => { if (guard.isCurrent(token)) apply(result); })
    .catch((reason: Error) => {
      if (reason.name !== "AbortError" && guard.isCurrent(token)) fail(reason.message);
    });
  return () => {
    // A late cleanup must not invalidate a newer request.
    if (guard.isCurrent(token)) guard.invalidate();
    controller.abort();
  };
}
