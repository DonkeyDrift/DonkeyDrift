// aidlite_cabi.cpp — 官方 Aidlux::Aidlite 的 C-ABI 外壳
// 目的：让没有官方 pybind11 绑定的解释器（本板为 3.12/3.11）用 ctypes 调 aidlite。
// 依据：/usr/local/include/aidlux/aidlite/aidlite.hpp (726 行，官方头)
#include "aidlux/aidlite/aidlite.hpp"

#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

using namespace Aidlux::Aidlite;

extern "C" {

/* ---------- 模块级 ---------- */
uint64_t al_get_abi_version(void) { return get_abi_version(); }

const char *al_get_library_version(void) {
    static std::string v = get_library_version();
    return v.c_str();
}

int32_t al_set_log_level(uint8_t level) { return set_log_level((LogLevel)level); }
int32_t al_log_to_stderr(void) { return log_to_stderr(); }
int32_t al_log_to_file(const char *path, int also_stderr) {
    return log_to_file(std::string(path ? path : ""), also_stderr != 0);
}
const char *al_last_log_msg(uint8_t level) { return last_log_msg((LogLevel)level); }

/* ---------- Model ---------- */
void *al_model_create(const char *path) {
    return (void *)Model::create_instance(std::string(path ? path : ""));
}

int32_t al_model_set_properties(void *model,
                                const uint32_t *in_dims, int32_t in_count, int32_t in_rank,
                                const uint32_t *out_dims, int32_t out_count, int32_t out_rank,
                                uint8_t data_type) {
    if (!model) return -1;
    std::vector<std::vector<uint32_t> > in_shapes, out_shapes;
    for (int32_t i = 0; i < in_count; ++i) {
        std::vector<uint32_t> s;
        for (int32_t j = 0; j < in_rank; ++j) s.push_back(in_dims[i * in_rank + j]);
        in_shapes.push_back(s);
    }
    for (int32_t i = 0; i < out_count; ++i) {
        std::vector<uint32_t> s;
        for (int32_t j = 0; j < out_rank; ++j) s.push_back(out_dims[i * out_rank + j]);
        out_shapes.push_back(s);
    }
    DataType dt = (DataType)data_type;
    return ((Model *)model)->set_model_properties(in_shapes, dt, out_shapes, dt);
}

void al_model_delete(void *model) { delete (Model *)model; }

/* ---------- Config（公开字段 struct） ---------- */
void *al_config_create(void) { return (void *)Config::create_instance(); }
void al_config_set_framework(void *cfg, uint8_t v) {
    if (cfg) ((Config *)cfg)->framework_type = (FrameworkType)v;
}
void al_config_set_accelerate(void *cfg, uint8_t v) {
    if (cfg) ((Config *)cfg)->accelerate_type = (AccelerateType)v;
}
void al_config_set_implement(void *cfg, uint8_t v) {
    if (cfg) ((Config *)cfg)->implement_type = (ImplementType)v;
}
void al_config_set_backend_extension(void *cfg, const char *p) {
    if (cfg && p) ((Config *)cfg)->backend_extension_config = std::string(p);
}
void al_config_set_performance_profile(void *cfg, const char *p) {
    if (cfg && p) ((Config *)cfg)->performance_profile = std::string(p);
}
void al_config_set_shared_buffer(void *cfg, int32_t v) {
    if (cfg) ((Config *)cfg)->qnn_shared_buffer = v;
}
void al_config_set_quantify_model(void *cfg, int32_t v) {
    if (cfg) ((Config *)cfg)->is_quantify_model = v;
}
void al_config_set_threads(void *cfg, int32_t v) {
    if (cfg) ((Config *)cfg)->number_of_threads = (int8_t)v;
}
int32_t al_config_get_framework(void *cfg) { return cfg ? (int32_t)((Config *)cfg)->framework_type : -1; }
int32_t al_config_get_accelerate(void *cfg) { return cfg ? (int32_t)((Config *)cfg)->accelerate_type : -1; }
void al_config_delete(void *cfg) { delete (Config *)cfg; }

/* ---------- InterpreterBuilder ---------- */
void *al_build_interpreter(void *model, void *cfg) {
    if (!model) return nullptr;
    std::unique_ptr<Interpreter> it =
        cfg ? InterpreterBuilder::build_interpreter_from_model_and_config((Model *)model, (Config *)cfg)
            : InterpreterBuilder::build_interpreter_from_model((Model *)model);
    return (void *)it.release();
}
void *al_build_interpreter_from_path(const char *path) {
    std::unique_ptr<Interpreter> it =
        InterpreterBuilder::build_interpreter_from_path(std::string(path ? path : ""));
    return (void *)it.release();
}

/* ---------- Interpreter ---------- */
int32_t al_interp_init(void *it) { return it ? ((Interpreter *)it)->init() : -1; }
int32_t al_interp_load_model(void *it) { return it ? ((Interpreter *)it)->load_model() : -1; }

/* is_native=false => 由 aidlite 做量化/反量化（与官方 pybind 绑定行为一致） */
int32_t al_interp_set_input(void *it, uint32_t idx, void *data) {
    return it ? ((Interpreter *)it)->set_input_tensor(idx, data, false) : -1;
}
int32_t al_interp_invoke(void *it) { return it ? ((Interpreter *)it)->invoke() : -1; }

int32_t al_interp_get_output(void *it, uint32_t idx, void **data, uint32_t *len) {
    if (!it) return -1;
    uint32_t l = 0;
    int32_t rc = ((Interpreter *)it)->get_output_tensor(idx, data, false, &l);
    if (len) *len = l;
    return rc;
}

int32_t al_interp_input_name_to_index(void *it, const char *name, uint32_t *idx) {
    if (!it) return -1;
    return ((Interpreter *)it)->input_tensor_name_to_index(std::string(name ? name : ""), idx);
}
int32_t al_interp_output_name_to_index(void *it, const char *name, uint32_t *idx) {
    if (!it) return -1;
    return ((Interpreter *)it)->output_tensor_name_to_index(std::string(name ? name : ""), idx);
}

/* 输出张量元信息：数量 / 名称（诊断用） */
int32_t al_interp_output_count(void *it, int32_t *count) {
    if (!it || !count) return -1;
    std::vector<std::vector<TensorInfo> > info;
    int32_t rc = ((Interpreter *)it)->get_output_tensor_info(info);
    if (rc != 0) return rc;
    *count = (!info.empty() && !info[0].empty()) ? (int32_t)info[0].size() : 0;
    return 0;
}
int32_t al_interp_output_name(void *it, int32_t i, char *buf, int32_t buflen) {
    if (!it || !buf || buflen <= 0) return -1;
    std::vector<std::vector<TensorInfo> > info;
    int32_t rc = ((Interpreter *)it)->get_output_tensor_info(info);
    if (rc != 0) return rc;
    if (info.empty() || i < 0 || (size_t)i >= info[0].size()) return -2;
    std::snprintf(buf, (size_t)buflen, "%s", info[0][i].name.c_str());
    return 0;
}

int32_t al_interp_destroy(void *it) { return it ? ((Interpreter *)it)->destroy() : -1; }
void al_interp_delete(void *it) { delete (Interpreter *)it; }

}  // extern "C"
