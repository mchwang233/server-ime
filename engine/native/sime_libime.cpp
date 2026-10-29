// C ABI over libime's pinyin decoder for the Python engine (ctypes).
// SPDX-License-Identifier: GPL-3.0-or-later (libime is LGPL-2.1-or-later)
//
// One sime_ime holds the dictionary and language model; each sime_ctx is one
// decoding state. Strings returned by sime_* stay valid until the next call on
// the same context; callers copy them at once.
#include <libime/core/prediction.h>
#include <libime/core/userlanguagemodel.h>
#include <libime/core/lattice.h>
#include <libime/core/segmentgraph.h>
#include <libime/pinyin/pinyincontext.h>
#include <libime/pinyin/pinyindictionary.h>
#include <libime/pinyin/pinyinime.h>
#include <libime/pinyin/pinyinprediction.h>
#include <libime/pinyin/shuangpinprofile.h>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

using namespace libime;

struct sime_ime {
    std::unique_ptr<PinyinIME> ime;
    PinyinPrediction prediction;
    std::string out;
};

struct sime_ctx {
    sime_ime *owner;
    std::unique_ptr<PinyinContext> context;
    std::string out;
    std::string input;  // what the context holds, to decode only the changed tail
    int shuangpin = -1;
    long flags = -1;    // fuzzy flags it was decoded with
};

extern "C" {

sime_ime *sime_open(const char *dict, const char *extra_dict, const char *lm, int nbest) {
    try {
        auto ime = std::make_unique<PinyinIME>(std::make_unique<PinyinDictionary>(),
                                               std::make_unique<UserLanguageModel>(lm));
        ime->dict()->load(PinyinDictionary::SystemDict, dict, PinyinDictFormat::Binary);
        ime->dict()->addEmptyDict();  // user dictionary slot, stays empty
        if (extra_dict && *extra_dict) {
            ime->dict()->addEmptyDict();
            ime->dict()->load(2, extra_dict, PinyinDictFormat::Binary);
        }
        ime->setNBest(nbest > 0 ? nbest : 2);
        ime->setScoreFilter(1.0f);
        ime->setPartialLongWordLimit(4);
        auto *handle = new sime_ime;
        handle->ime = std::move(ime);
        handle->prediction.setUserLanguageModel(handle->ime->model());
        handle->prediction.setPinyinDictionary(handle->ime->dict());
        return handle;
    } catch (...) {
        return nullptr;
    }
}

void sime_close(sime_ime *ime) { delete ime; }

// Search breadth: N-best sentences, beam and frame sizes (0 keeps the current value).
void sime_tune(sime_ime *ime, int nbest, int beam, int frame) {
    if (nbest > 0) ime->ime->setNBest(nbest);
    if (beam > 0) ime->ime->setBeamSize(beam);
    if (frame > 0) ime->ime->setFrameSize(frame);
}

int sime_beam(sime_ime *ime) { return static_cast<int>(ime->ime->beamSize()); }
int sime_frame(sime_ime *ime) { return static_cast<int>(ime->ime->frameSize()); }

// Ziranma=0 MS=1 Ziguang=2 ABC=3 Zhongwenzhixing=4 PinyinJiajia=5 Xiaohe=6
void sime_set_shuangpin(sime_ime *ime, int profile) {
    ime->ime->setShuangpinProfile(
        std::make_shared<ShuangpinProfile>(static_cast<ShuangpinBuiltinProfile>(profile)));
}

// Adds a word to the extra dictionary (index 2 if loaded, else the user slot).
int sime_add_word(sime_ime *ime, const char *pinyin, const char *text, float cost) {
    try {
        size_t idx = ime->ime->dict()->dictSize() > 2 ? 2 : PinyinDictionary::UserDict;
        ime->ime->dict()->addWord(idx, pinyin, text, cost);
        return 1;
    } catch (...) {
        return 0;
    }
}

sime_ctx *sime_ctx_new(sime_ime *ime) {
    auto *ctx = new sime_ctx;
    ctx->owner = ime;
    ctx->context = std::make_unique<PinyinContext>(ime->ime.get());
    return ctx;
}

void sime_ctx_free(sime_ctx *ctx) { delete ctx; }

// Fuzzy flags are model-wide; each context notices a change and decodes afresh.
int sime_decode(sime_ctx *ctx, const char *input, int shuangpin, unsigned flags) {
    try {
        auto &ime = *ctx->owner->ime;
        if (static_cast<unsigned>(ime.fuzzyFlags()) != flags) {
            ime.setFuzzyFlags(static_cast<PinyinFuzzyFlag>(flags));
        }
        std::string_view next(input);
        size_t common = 0;
        if (ctx->shuangpin == (shuangpin != 0) && ctx->flags == static_cast<long>(flags)) {
            while (common < ctx->input.size() && common < next.size() &&
                   ctx->input[common] == next[common]) {
                ++common;
            }
        }
        // Typing more letters keeps the lattice built for the letters before them;
        // any other change decodes afresh, which erasing does not match exactly.
        if (common == 0 || common < ctx->input.size()) {
            common = 0;
            ctx->context->clear();
            ctx->context->setUseShuangpin(shuangpin != 0);
            ctx->shuangpin = shuangpin != 0;
            ctx->flags = flags;
        }
        ctx->input = std::string(next);
        if (common < next.size()) {
            ctx->context->type(next.substr(common));
        }
        return static_cast<int>(ctx->context->candidates().size());
    } catch (...) {
        ctx->input.clear();
        ctx->shuangpin = -1;
        return -1;
    }
}

const char *sime_text(sime_ctx *ctx, int i) {
    ctx->out = ctx->context->candidates().at(i).toString();
    return ctx->out.c_str();
}

// Input bytes the candidate covers, from the start of the decoded input.
int sime_end(sime_ctx *ctx, int i) {
    const auto &sentence = ctx->context->candidates().at(i).sentence();
    return sentence.empty() ? 0 : static_cast<int>(sentence.back()->to()->index());
}

const char *sime_pinyin(sime_ctx *ctx, int i) {
    ctx->out = ctx->context->candidateFullPinyin(i);
    return ctx->out.c_str();
}

// Whether the language model knows `word` (so it can be prediction context).
int sime_known(sime_ime *ime, const char *word) {
    const auto *model = ime->ime->model();
    return model->index(word) != model->unknown();
}

// Next words after the words in `history` (tab separated), tab separated.
const char *sime_predict(sime_ime *ime, const char *history, int max) {
    std::vector<std::string> words;
    std::stringstream in(history ? history : "");
    for (std::string word; std::getline(in, word, '\t');) {
        if (!word.empty()) words.push_back(word);
    }
    ime->out.clear();
    try {
        for (const auto &word : ime->prediction.predict(words, max)) {
            if (!ime->out.empty()) ime->out += '\t';
            ime->out += word;
        }
    } catch (...) {
    }
    return ime->out.c_str();
}

}
