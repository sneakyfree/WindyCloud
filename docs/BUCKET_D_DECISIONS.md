# Wave 7 — Bucket D decisions queue

**Triage found 0 PRs strictly blocked on a Grant decision.**

The closest is **[#10 G7 optional JWT aud/iss validation](https://github.com/sneakyfree/WindyCloud/pull/10)**,
which is back-compat-safe to merge (defaults are empty → no-op) but
needs a coordination call before the env vars get set to non-empty
values. I filed it in Bucket C as HIGH-RISK since the crypto review
itself wants eyes, but the *decision* for Grant is separable:

## #10 G7 — JWT audience/issuer values

**What needs deciding (post-merge):**
- `WINDY_CLOUD_EXPECTED_AUDIENCE` — the `aud` claim Pro should mint on
  Cloud-destined tokens. Candidates: `"windy-cloud"`, `"cloud"`,
  `"https://cloud.windyfly.ai"`, `"windycloud.com"`. Pick one string;
  any choice works as long as it matches what Pro emits.
- `WINDY_PRO_EXPECTED_ISSUER` — Pro's canonical issuer URL. Likely
  `"https://windyword.ai"` but confirm with Pro's current JWT
  template.
- `ETERNITAS_EXPECTED_ISSUER` — Eternitas' canonical issuer URL.
  Likely `"https://eternitas.ai"` but confirm against
  `/Users/thewindstorm/eternitas/docs/trust-api.md`.

**Implications of deferring:** zero. The merge ships with all three
env vars empty, matching pre-Wave-7 behaviour. Cross-product token
confusion remains theoretically possible until the values are set, but
the attack surface hasn't changed since pre-merge.

**Implications of picking now:** Pro needs to update its JWT template
to include the chosen `aud` / `iss` before the env vars flip to
non-empty, otherwise every Pro-minted token 401s on Cloud. Coordinate
the switch as a three-step rollout: (1) Pro starts emitting the new
claims (both-compat); (2) Cloud sets the env vars; (3) verify; (4)
Pro drops the old no-claim template.

**Recommendation:** merge #10 now as Bucket C, pick the values in a
focused cross-team call post-launch, roll out in the 4-step pattern
above.

---

## No other Bucket D items

Every other Wave 7 PR is either mergeable without decisions (Bucket A
+ B) or needs a code review rather than a Grant decision (Bucket C).
Nothing is stuck.
