/* draft.cpp -- the static draft-depth policy. See draft.h for why it is static.
 */
#include "draft.h"

namespace rad {

int DraftController::configure(const Params& p) {
    if (p.max_depth < 0 || p.max_depth > RAD_SCHED_MAX_SPEC) {
        RAD_ERR("draft depth %d is outside 0..%d -- the verify kernel band is %d query rows",
                p.max_depth, RAD_SCHED_MAX_SPEC, RAD_SCHED_MAX_SPEC);
        return RAD_E_INVAL;
    }
    p_ = p;
    tot_drafted_ = tot_accepted_ = 0;
    for (int j = 0; j < RAD_SCHED_MAX_SPEC; ++j) { reach_[j] = 0; hit_[j] = 0; }
    seen_ = 0;
    ema_accept_len_ = 2.0f;
    return RAD_OK;
}

void DraftController::observe(int drafted, int accepted, int active_seqs) {
    if (drafted <= 0) return;
    if (drafted > RAD_SCHED_MAX_SPEC) drafted = RAD_SCHED_MAX_SPEC;
    if (accepted < 0) accepted = 0;
    if (accepted > drafted) accepted = drafted;
    tot_drafted_  += drafted;
    tot_accepted_ += accepted;

    /* Scaled EMA update based on active concurrency:
     * When active_seqs > 1, each sequence contributes alpha / active_seqs so that
     * the total batch update per engine step has effective weight alpha = 0.2 */
    const float eff_alpha = 0.2f / (float)std::max(1, active_seqs);
    ema_accept_len_ = (1.0f - eff_alpha) * ema_accept_len_ + eff_alpha * (float)accepted;

    /* Position j was EVALUATED only if every position before it was accepted, so this verify
     * produces exactly: 0..accepted-1 evaluated and accepted, and -- when the prefix was not the
     * whole draft -- position `accepted` evaluated and rejected. Nothing past that was reached. */
    const int last = accepted < drafted ? accepted : drafted - 1;
    for (int j = 0; j <= last; ++j) {
        ++reach_[j];
        if (j < accepted) ++hit_[j];
    }
    if (drafted > seen_) seen_ = drafted;
}

}  /* namespace rad */
