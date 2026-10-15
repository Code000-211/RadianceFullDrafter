#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include <thread>
#include <sstream>
#include <any>
#include <filesystem>
#include <iostream>
#include <iomanip>
#include <random>
#include <atomic>
#include <chrono>
#include <unordered_map>
#include <algorithm>

#if __has_include("arch/common/rad_tree_candidate.h")
#include "arch/common/rad_tree_candidate.h"
#elif __has_include("../arch/common/rad_tree_candidate.h")
#include "../arch/common/rad_tree_candidate.h"
#endif

#include "sample/accept.h"
#include "sched/draft.h"
#include "sched/advance_impl.h"
#include "diag.h"

#define private public
#include "sched/scheduler.h"
#include "sched/batch.h"
#include "engine.h"
#undef private

#include "rad_core.h"


#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #x); std::abort(); } } while (0)
using namespace rad;
using namespace radiance;
struct MinimalFakeKV : public rad::IKVManager {
    std::unordered_set<uint64_t> seqs;
    int add_sequence(uint64_t id) override { seqs.insert(id); return RAD_OK; }
    bool has_sequence(uint64_t id) const override { return seqs.count(id) != 0; }
    void free_sequence(uint64_t id) override { seqs.erase(id); }
    int ensure(uint64_t, int64_t) override { return RAD_OK; }
    int adopt(uint64_t, int32_t, const std::vector<int32_t>&, int64_t) override { return RAD_OK; }
    int preempt(uint64_t) override { return RAD_OK; }
    bool can_ever_fit(int64_t) const override { return true; }
    const std::vector<int32_t>& block_table(uint64_t, int32_t) const override {
        static const std::vector<int32_t> s_empty;
        return s_empty;
    }
    int32_t state_slot(uint64_t, int32_t) const override { return -1; }
    int state_index_row(uint64_t, int32_t, int32_t*, int) const override { return 0; }
    int64_t state_index_width(int32_t) const override { return 0; }
    int64_t free_blocks(int32_t) const override { return 1000; }
    int64_t total_blocks(int32_t) const override { return 1000; }
    int64_t held_blocks(int32_t) const override { return 0; }
    int64_t pool_bytes(int32_t) const override { return 1000000; }
    int64_t pool_bytes_used(int32_t) const override { return 0; }
    int64_t pool_bytes_carved(int32_t) const override { return 1000000; }
    int64_t block_tokens(int32_t) const override { return 16; }
    int rollback_calls = 0;
    int64_t last_valid = -1;
    int rollback(uint64_t, int64_t valid) override {
        ++rollback_calls; last_valid = valid; return RAD_OK;
    }
    int64_t first_block_pos(uint64_t, int32_t) const override { return 0; }
    int64_t take_table_changes(uint64_t, int32_t) const override { return 0; }
};


static void test_block_anchor() {
    MinimalFakeKV kv;
    Scheduler sched;
    sched.kv_ = &kv;
    sched.cfg_.max_tok = 128;
    CHECK(sched.draft_.configure({12, false}) == RAD_OK);
    auto req = std::make_unique<Request>();
    req->id = 7101; req->prompt = {17, 18}; req->output = {42, 0};
    req->n_computed = 137; req->state = ReqState::Running; req->may_speculate = true;
    CHECK(sched.add(std::move(req)) == RAD_OK);
    const int slot = sched.by_id_.at(7101);
    auto& s = *sched.reqs_[slot];
    s.running = true; s.req->state = ReqState::Running;
    StepEntry e{}; e.seq = 7101; e.slot = slot; e.card = 0;
    e.ctx_len = 0; e.n_tokens = 1; e.produces_token = true;
    sched.plan_.e.push_back(e);
    Scheduler::BlockRow row;
    CHECK(row.anchor_token == -1 && row.root_pos == -1);
    CHECK(sched.block_begin(13, 12, 0, 99, &row, 1) == 1);
    CHECK(row.anchor_token == 0 && row.root_pos == 137 && row.seq == 7101);
    s.req->output.back() = 123;
    s.req->n_computed = 149;
    CHECK(sched.block_begin(13, 12, 0, 99, &row, 1) == 1);
    CHECK(row.anchor_token == 123 && row.root_pos == 149);
    // Multi-stage block drafter (2 x 6 = 12, block=7, depth=12)
    CHECK(sched.block_begin(7, 12, 0, 99, &row, 1) == 1);
    CHECK(row.anchor_token == 123 && row.root_pos == 149);
    // Invalid multi-stage drafter (13 % 6 != 0)
    CHECK(sched.block_begin(7, 13, 0, 99, &row, 1) == 0);
    // Invalid block < 2
    CHECK(sched.block_begin(1, 12, 0, 99, &row, 1) == 0);
    // Invalid geometry with depth < block: block=10, depth=3
    CHECK(sched.block_begin(10, 3, 0, 99, &row, 1) == 0);
    s.req->output.clear();
    CHECK(sched.block_begin(13, 12, 0, 99, &row, 1) == 0);
}
static void test_tree_publication() {
    Scheduler sched;
    auto req = std::make_unique<Request>(); req->id = 7102;
    req->prompt = {5}; req->may_speculate = true; req->max_tokens = 3;
    CHECK(sched.add(std::move(req)) == RAD_OK);
    const int slot = sched.by_id_.at(7102);
    auto& s = *sched.reqs_[slot];
    uint32_t drafts[12]; for (int i=0;i<12;++i) drafts[i]=100+i;
    CandidateTree tree; tree.build_linear(0, drafts, 12);
    CHECK(sched.set_draft_tree(7102, tree, 137) == RAD_OK);
    ActiveTreeRecord rec;
    CHECK(TreeRegistry::instance().get(7102, &rec));
    CHECK(s.n_draft == 2 && rec.tree.node_count() == 3);
    CHECK(s.draft[0] == 100 && s.draft[1] == 101);
    CHECK(rec.tree[0].token_id == 0 && rec.positions[0] == 137 && rec.positions[2] == 139);
    s.req->max_tokens = 1;
    CHECK(sched.set_draft_tree(7102, tree, 137) == RAD_OK);
    CHECK(!TreeRegistry::instance().get(7102, &rec));
    CHECK(s.n_draft == 0 && !s.has_draft_tree && s.req->draft == nullptr);
    s.req->max_tokens = 20;
    CHECK(sched.set_draft_tree(7102, tree, 137) == RAD_OK);
    s.req->may_speculate = false;
    CHECK(sched.set_draft_tree(7102, tree, 137) == RAD_OK);
    CHECK(!TreeRegistry::instance().get(7102, &rec));
    s.req->may_speculate = true;
    tree.build_linear(0, nullptr, 0);
    CHECK(sched.set_draft_tree(7102, tree, 137) == RAD_OK);
    CHECK(!TreeRegistry::instance().get(7102, &rec));
    CHECK(sched.set_draft_tree(999999, tree, 137) == RAD_E_NOTFOUND);
}
static void test_token_ids_are_not_eos() {
    for (uint32_t token : {0u, 151643u, 151645u}) {
        uint32_t draft[] = {token, 72};
        CandidateTree tree; tree.build_linear(19, draft, 2);
        int32_t preds[] = {static_cast<int32_t>(token), 72, 81};
        int32_t out[4] = {-1,-1,-1,-1}, accepted=-1, bonus=-1;
        CHECK(accept_tree_greedy(tree, preds, 3, out, &accepted, &bonus) == RAD_OK);
        CHECK(accepted == 2 && out[0] == static_cast<int32_t>(token));
        CHECK(out[1] == 72 && out[2] == 81 && bonus == 81);
    }
}
static void test_short_candidate_buffers() {
    for (size_t n=0;n<=15;++n) {
        std::vector<uint32_t> candidates(n); for(size_t i=0;i<n;++i)candidates[i]=100+i;
        for(int mode=0;mode<3;++mode) {
            CandidateTree tree;
            if(mode<2)tree.build_top2(0,candidates.data(),mode==1,n);
            else tree.build_top4(0,candidates.data(),n);
            CHECK(tree.node_count()==n+1);
            for(size_t i=1;i<=n;++i)CHECK(tree[i].token_id==candidates[i-1]);
        }
    }
}
static void test_unwired_sidecar_rejected() {
    const char* prev = std::getenv("RADIANCE_FULLDRAFTER_SIDECAR");
    const bool had = prev != nullptr; const std::string saved = prev ? prev : "";
    setenv("RADIANCE_FULLDRAFTER_SIDECAR", "/does/not/read/checkpoint.safetensors", 1);
    { Config cfg; Engine engine(cfg); CHECK(engine.step_state_init() == RAD_E_INVAL); }
    if(had)setenv("RADIANCE_FULLDRAFTER_SIDECAR",saved.c_str(),1);
    else unsetenv("RADIANCE_FULLDRAFTER_SIDECAR");
}

// Exercise real collect_step -> commit, not a simulated acceptance loop.
static void test_rollback_owner_and_emission() {
    for (bool tree_mode : {false, true})
    for (int accepted : {0, 1, 3})
    for (int pipeline : {0, 1, 2}) {
        Program program; Config cfg; Engine engine(cfg);
        auto owned = std::make_unique<MinimalFakeKV>();
        auto* kv = owned.get(); engine.kv_iface_ = std::move(owned);
        auto& sched = engine.sched_; sched.kv_ = kv; sched.prog_ = &program;
        auto req = std::make_unique<Request>(); req->id = 7201;
        req->prompt = {8, 9}; req->output = {19}; req->n_computed = 17;
        req->may_speculate = true; req->max_tokens = 100;
        CHECK(sched.add(std::move(req)) == RAD_OK);
        const int slot = sched.by_id_.at(7201); auto& s = *sched.reqs_[slot];
        s.running = true; s.req->state = ReqState::Running; s.entry = 0;
        s.entry_next = pipeline == 2 ? 0 : -1;
        sched.next_open_ = pipeline != 0; sched.step_open_ = true;
        uint32_t drafts[] = {31,32,33}; CandidateTree tree;
        tree.build_linear(19, drafts, 3);
        CHECK(sched.set_draft_tree(7201, tree, 17) == RAD_OK);
        if (!tree_mode) TreeRegistry::instance().clear(7201);
        StepEntry e{}; e.seq = 7201; e.slot = slot; e.card = 0;
        e.ctx_len = 17; e.n_tokens = 4; e.n_spec = 3; e.n_draft = 3;
        e.req = s.req.get(); e.draft = s.draft; e.produces_token = true;
        sched.plan_.e.push_back(e);
        int32_t sampled[] = {31,32,33,77}; sampled[accepted] = 77;
        Engine::StepOut so; so.n_rows = 4; so.rb = sampled; so.first_row = {0};
        RadBatch batch{}; batch.n_seq = 1; batch.n_spec = 3;
        CHECK(engine.collect_step(&batch, so) == RAD_OK);
        CHECK(kv->rollback_calls == 0); // Collector must never free pipelined KV.
        CHECK(so.accepted[0] == accepted && so.token[0] == 77 && so.eos[0] == 0);
        Scheduler::StepResult result{}; result.n_seq = 1;
        result.n_accepted = so.accepted.data(); result.token = so.token.data(); result.eos = so.eos.data();
        CHECK(sched.commit(result) == RAD_OK);
        const bool rollback = accepted < 3 && pipeline != 2;
        CHECK(kv->rollback_calls == (rollback ? 1 : 0));
        if (rollback) CHECK(kv->last_valid == 18 + accepted);
        CHECK(s.req->n_computed == 18 + accepted);
        CHECK(s.req->output.size() == static_cast<size_t>(accepted + 2));
        CHECK(s.req->output[0] == 19 && s.req->output.back() == 77);
        for(int i=0;i<accepted;++i) CHECK(s.req->output[i+1] == static_cast<int32_t>(drafts[i]));
        sched.next_open_ = false; s.entry_next = -1;
    }
}
static void test_linear_proposal_contract() {
    uint32_t drafts[] = {31,32,33};
    CandidateTree tree; tree.build_linear(19, drafts, 3);
    uint32_t tokens[16]{}, positions[16]{}; uint16_t masks[16]{};
    tree.populate_tensors(tokens, masks, positions, 137);
    for (int i=0;i<4;++i) {
        CHECK(tree[i].parent_id == i-1 && tree[i].depth == i);
        CHECK(positions[i] == static_cast<uint32_t>(137+i));
        CHECK(masks[i] == (1u << (i+1))-1);
    }
    int32_t preds[] = {31,32,33,77}, out[4]{}, accepted=-1, bonus=-1;
    CHECK(accept_tree_greedy(tree,preds,4,out,&accepted,&bonus) == RAD_OK);
    CHECK(accepted == 3 && bonus == 77);
}

static void test_recurrent_tree_guard() {
    for (int kind : {RAD_KV_LINEAR, RAD_KV_CONV, RAD_KV_FULL}) {
        Program program;
        KVGroupInfo group{}; group.decl.kind = kind;
        program.kv_groups.push_back(group);
        program.branched_tree_supported = kind != RAD_KV_FULL;
        Scheduler sched; sched.prog_ = &program;
        auto request = std::make_unique<Request>();
        request->id = 7301; request->prompt = {1}; request->may_speculate = true;
        CHECK(sched.add(std::move(request)) == RAD_OK);
        uint32_t tokens[3] = {2,3,4}; CandidateTree tree;
        tree.build_linear(1,tokens,3);
        CHECK(sched.set_draft_tree(7301,tree,10) == RAD_OK);
        CHECK(TreeRegistry::instance().get(7301,nullptr));
        tree.build_top2(1,tokens,false,3);
        if (kind == RAD_KV_FULL) {
            program.branched_tree_supported = true;
            CHECK(sched.set_draft_tree(7301,tree,10) == RAD_OK);
            CHECK(TreeRegistry::instance().get(7301,nullptr));
            program.branched_tree_supported = false;
        }
        CHECK(sched.set_draft_tree(7301,tree,10) == RAD_E_UNSUPPORTED);
        CHECK(!TreeRegistry::instance().get(7301,nullptr));
        const auto& state = *sched.reqs_[sched.by_id_.at(7301)];
        CHECK(!state.has_draft_tree && state.n_draft == 0 && state.req->draft == nullptr);
        tree.build_linear(1,tokens,3);
        CHECK(sched.set_draft_tree(7301,tree,10) == RAD_OK);
        TreeRegistry::instance().clear(7301);
    }
}

static void test_concurrent_batch_deterministic_indexing() {
    Program program;
    MinimalFakeKV kv;
    Scheduler sched;
    sched.kv_ = &kv;
    sched.prog_ = &program;
    sched.hit_holes_draft_ = false;
    sched.cfg_.max_tok = 512;
    CHECK(sched.draft_.configure({12, false}) == RAD_OK);

    // Create 3 requests in concurrent execution:
    // Req 1: id=8001, ctx_len=10, K=3, accepted=1 (a < K, partial rejection)
    // Req 2: id=8002, ctx_len=20, K=2, accepted=2 (a = K, full acceptance)
    // Req 3: id=8003, ctx_len=30, K=4, accepted=0 (a = 0, complete rejection)
    auto r1 = std::make_unique<Request>();
    r1->id = 8001; r1->prompt = {1, 2}; r1->output = {100}; r1->n_computed = 10;
    r1->may_speculate = true; r1->state = ReqState::Running;
    CHECK(sched.add(std::move(r1)) == RAD_OK);
    const int slot1 = sched.by_id_.at(8001);
    auto& s1 = *sched.reqs_[slot1]; s1.running = true; s1.req->state = ReqState::Running; s1.entry = 0;

    auto r2 = std::make_unique<Request>();
    r2->id = 8002; r2->prompt = {3, 4}; r2->output = {200}; r2->n_computed = 20;
    r2->may_speculate = true;
    CHECK(sched.add(std::move(r2)) == RAD_OK);
    const int slot2 = sched.by_id_.at(8002);
    auto& s2 = *sched.reqs_[slot2]; s2.running = true; s2.req->state = ReqState::Running; s2.entry = 1;

    auto r3 = std::make_unique<Request>();
    r3->id = 8003; r3->prompt = {5, 6}; r3->output = {300}; r3->n_computed = 30;
    r3->may_speculate = true;
    CHECK(sched.add(std::move(r3)) == RAD_OK);
    const int slot3 = sched.by_id_.at(8003);
    auto& s3 = *sched.reqs_[slot3]; s3.running = true; s3.req->state = ReqState::Running; s3.entry = 2;

    int32_t draft1[] = {101, 102, 103};
    int32_t draft2[] = {201, 202};
    int32_t draft3[] = {301, 302, 303, 304};
    CHECK(sched.set_draft(8001, draft1, 3) == RAD_OK);
    CHECK(sched.set_draft(8002, draft2, 2) == RAD_OK);
    CHECK(sched.set_draft(8003, draft3, 4) == RAD_OK);

    StepEntry e1{}; e1.seq = 8001; e1.slot = slot1; e1.card = 0;
    e1.ctx_len = 10; e1.n_tokens = 4; e1.n_spec = 3; e1.n_draft = 3;
    e1.req = s1.req.get(); e1.draft = s1.draft; e1.produces_token = true;

    StepEntry e2{}; e2.seq = 8002; e2.slot = slot2; e2.card = 1;
    e2.ctx_len = 20; e2.n_tokens = 3; e2.n_spec = 2; e2.n_draft = 2;
    e2.req = s2.req.get(); e2.draft = s2.draft; e2.produces_token = true;

    StepEntry e3{}; e3.seq = 8003; e3.slot = slot3; e3.card = 2;
    e3.ctx_len = 30; e3.n_tokens = 5; e3.n_spec = 4; e3.n_draft = 4;
    e3.req = s3.req.get(); e3.draft = s3.draft; e3.produces_token = true;

    sched.plan_.e = {e1, e2, e3};
    sched.running_ = {slot1, slot2, slot3};
    sched.step_open_ = true;

    int32_t accepted[] = {1, 2, 0};
    int32_t tokens[] = {999, 888, 777};
    uint8_t eos[] = {0, 0, 0};
    Scheduler::StepResult res{};
    res.n_seq = 3;
    res.n_accepted = accepted;
    res.token = tokens;
    res.eos = eos;

    CHECK(sched.commit(res) == RAD_OK);

    CHECK(s1.req->n_accepted == 1);
    CHECK(s1.req->n_computed == 12);
    CHECK(s1.req->output.back() == 999);

    CHECK(s2.req->n_accepted == 2);
    CHECK(s2.req->n_computed == 23);
    CHECK(s2.req->output.back() == 888);

    CHECK(s3.req->n_accepted == 0);
    CHECK(s3.req->n_computed == 31);
    CHECK(s3.req->output.back() == 777);

    Scheduler::BlockRow rows[3];
    int n_rows = sched.block_begin(13, 12, 0, 99, rows, 3);
    CHECK(n_rows == 3);

    CHECK(rows[0].seq == 8001);
    CHECK(rows[0].tap_row == 1);
    CHECK(rows[0].anchor_token == 999);
    CHECK(rows[0].root_pos == 12);

    CHECK(rows[1].seq == 8002);
    CHECK(rows[1].tap_row == 6);
    CHECK(rows[1].anchor_token == 888);
    CHECK(rows[1].root_pos == 23);

    CHECK(rows[2].seq == 8003);
    CHECK(rows[2].tap_row == 7);
    CHECK(rows[2].anchor_token == 777);
    CHECK(rows[2].root_pos == 31);

    // The query pass reads these through StepEntry::src_row -> RadBatch::draft_out_ids.
    CHECK(sched.block_.size() == 3);
    CHECK(sched.block_[0].tap_row == 1);
    CHECK(sched.block_[1].tap_row == 6);
    CHECK(sched.block_[2].tap_row == 7);
}

static void test_block_device_row_patches() {
    struct Slab {
        int32_t tok[24], pos[24], ctx[3], dout[3], sid[3], cu[3], q[3], rows[12];
    } slab{};
    std::fill(slab.tok, slab.tok + 24, 99);
    std::fill(slab.pos, slab.pos + 24, 137);
    std::fill(slab.ctx, slab.ctx + 3, 137);
    std::fill(slab.dout, slab.dout + 3, -1);
    slab.sid[0] = 2; slab.sid[1] = 0; slab.sid[2] = 1;
    slab.cu[0] = 2; slab.cu[1] = 9; slab.cu[2] = 16;
    std::fill(slab.q, slab.q + 3, 7);
    slab.rows[0] = 1; slab.rows[1] = 1; slab.rows[2] = 0;
    slab.rows[3] = 0; slab.rows[4] = 4; slab.rows[5] = 7;
    StepSlot slots[3]{};
    slots[2].acc = 0; slots[2].tok[0] = 0;
    slots[0].acc = 2; slots[0].tok[0] = 123;
    slots[1].acc = 4; slots[1].tok[0] = 456;
    const Slab before = slab;
    StepSlot slots_before[3];
    std::memcpy(slots_before, slots, sizeof(slots));
    AdvanceArgs args{};
    args.mode = ADV_BLOCK; args.n_seq = 3; args.row_pitch = 3;
    args.slab = reinterpret_cast<char*>(&slab); args.st = slots;
    args.tok_off = offsetof(Slab, tok); args.pos_off = offsetof(Slab, pos);
    args.ctx_off = offsetof(Slab, ctx); args.dout_off = offsetof(Slab, dout);
    args.sid_off = offsetof(Slab, sid); args.cu_off = offsetof(Slab, cu);
    args.q_off = offsetof(Slab, q); args.row_off = offsetof(Slab, rows);
    CHECK(ADV_BLOCK == 6);
    for (int i = 0; i < 3; ++i) adv_row(args, i);
    CHECK(slab.tok[2] == 0 && slab.tok[9] == 123);
    CHECK(slab.dout[0] == 0 && slab.dout[1] == 6 && slab.dout[2] == -1);
    Slab expected = before;
    expected.tok[2] = 0; expected.tok[9] = 123;
    expected.dout[0] = 0; expected.dout[1] = 6;
    CHECK(std::memcmp(&slab, &expected, sizeof(slab)) == 0);
    CHECK(std::memcmp(slots, slots_before, sizeof(slots)) == 0);
}

static void test_block_precommit_and_committed_anchor() {
    struct RecordingKV : MinimalFakeKV {
        std::vector<std::pair<uint64_t, int64_t>> reservations;
        int ensure(uint64_t seq, int64_t end) override {
            reservations.emplace_back(seq, end); return RAD_OK;
        }
    } kv;
    Scheduler sched;
    sched.kv_ = &kv; sched.hit_holes_draft_ = false; sched.cfg_.max_tok = 128;
    CHECK(sched.draft_.configure({12, false}) == RAD_OK);
    for (int i = 0; i < 2; ++i) {
        auto req = std::make_unique<Request>();
        req->id = 8101 + i; req->prompt = {17}; req->n_computed = 20 + 10 * i;
        req->may_speculate = true;
        CHECK(sched.add(std::move(req)) == RAD_OK);
        const int slot = sched.by_id_.at(8101 + i);
        auto& s = *sched.reqs_[slot];
        s.running = true; s.req->state = ReqState::Running;
        StepEntry e{}; e.seq = 8101 + i; e.slot = slot;
        e.ctx_len = 20 + 10 * i; e.n_spec = i == 0 ? 3 : 2;
        e.n_tokens = 1 + e.n_spec; e.produces_token = true;
        sched.plan_.e.push_back(e);
    }
    sched.plan_.phase = RAD_PHASE_DECODE;
    Scheduler::BlockRow rows[2];
    CHECK(sched.block_begin(7, 12, 0, 99, rows, 2, true) == 2);
    CHECK(kv.reservations.size() == 2);
    CHECK(kv.reservations[0].first == 8101 && kv.reservations[0].second == 36);
    CHECK(kv.reservations[1].first == 8102 && kv.reservations[1].second == 45);
    CHECK(sched.block_[0].dev && sched.block_[0].dev_tok == 0);
    CHECK(sched.block_[1].dev && sched.block_[1].dev_tok == 4);
    for (const auto& row : rows)
        CHECK(row.anchor_token == -1 && row.root_pos == -1 && row.tap_row == -1);
    kv.reservations.clear();
    CHECK(sched.block_begin(13, 12, 0, 99, rows, 2, true) == 2);
    CHECK(kv.reservations.size() == 2);
    CHECK(kv.reservations[0].second == 37 && kv.reservations[1].second == 46);
    kv.reservations.clear();
    sched.ctx_limit_ = 44;
    CHECK(sched.block_begin(7, 12, 0, 99, rows, 2, true) == 1);
    CHECK(kv.reservations.size() == 1 && kv.reservations[0].second == 36);
    sched.ctx_limit_ = 0;
    kv.reservations.clear();
    sched.plan_.phase = RAD_PHASE_PREFILL;
    CHECK(sched.block_begin(7, 12, 0, 99, rows, 2, true) == 0);
    sched.plan_.phase = RAD_PHASE_DECODE;
    sched.plan_.e[1].is_prefill = true;
    CHECK(sched.block_begin(7, 12, 0, 99, rows, 2, true) == 0);
    sched.plan_.e[1].is_prefill = false;
    sched.plan_.e[1].produces_token = false;
    CHECK(sched.block_begin(7, 12, 0, 99, rows, 2, true) == 0);
    CHECK(kv.reservations.empty() && sched.block_.empty());
    const int slot = sched.by_id_.at(8101);
    auto& req = *sched.reqs_[slot]->req;
    int32_t token = -1; int64_t pos = -1;
    CHECK(!sched.block_committed_anchor(8101, slot, &token, &pos));
    req.output = {99, 0}; req.n_computed = 24;
    CHECK(sched.block_committed_anchor(8101, slot, &token, &pos));
    CHECK(token == 0 && pos == 24);
    req.state = ReqState::Finished;
    CHECK(!sched.block_committed_anchor(8101, slot, &token, &pos));
    req.state = ReqState::Running; req.id = 8199;
    CHECK(!sched.block_committed_anchor(8101, slot, &token, &pos));
    CHECK(sched.block_committed_anchor(8199, slot, &token, &pos));
    CHECK(!sched.block_committed_anchor(8199, -1, &token, &pos));
    req.id = 8101;
}

static void test_block_depth_rejection_invariance() {
    for (bool tree : {false, true}) {
        SchedReq req;
        req.has_draft_tree = tree;
        const int cap = tree ? 5 : 12;
        for (int accepted : {12, 0, 0, 0, 0, 0}) {
            req.observe_draft(12, accepted);
            CHECK(req.suggest_depth(12, true, false, cap) == 8);
            CHECK(req.suggest_depth(12, true, true, cap) == 4);
            CHECK(req.suggest_depth(3, true, false, cap) == 3);
            CHECK(req.suggest_depth(3, true, true, cap) == 3);
            CHECK(req.suggest_depth(12, false, false, cap) == 8);
            CHECK(req.suggest_depth(12, false, true, cap) == 4);
        }
    }
    SchedReq small;
    CHECK(small.suggest_depth(3, false, false, 5) == 3);
    CHECK(small.suggest_depth(3, false, true, 5) == 3);
}

int main() {
    test_block_device_row_patches();
    test_block_precommit_and_committed_anchor();
    test_block_depth_rejection_invariance();
    test_concurrent_batch_deterministic_indexing();
    test_recurrent_tree_guard();
    test_rollback_owner_and_emission(); test_linear_proposal_contract();
    test_block_anchor(); test_tree_publication(); test_token_ids_are_not_eos();
    test_short_candidate_buffers(); test_unwired_sidecar_rejected();
    std::puts("PASS: 12 drafter CPU regression groups (no device initialization)");
}
