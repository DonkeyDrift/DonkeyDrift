# scripts/aidlite_cabi —— aidlite 的「C-ABI 外壳 + ctypes 门面」

让**工程自己的 Python 版本**（如 3.12）能 `import aidlite`，从而在单环境里跑 NPU。

## 为什么需要它

CPython 的**扩展模块 ABI 按版本锁死**。本板镜像提供的官方绑定是

    /usr/local/lib/python3.10/dist-packages/aidlite/soaidlitesdk.cpython-310-aarch64-linux-gnu.so

文件名的 `cpython-310` 是硬约束 —— 3.11/3.12 加载它必定失败：

    ImportError: Python version mismatch: module was compiled for Python 3.10,
                 but the interpreter version is incompatible: 3.12.14

而本工程 `python_requires >= 3.11`（且 `donkeycar/__init__.py` 有硬门槛）、AidLux 又不提供任何
py3.12 包 ⇒ 工程版本跑不了 NPU。三种解法里本目录是第三种：

| 方案 | 代价 |
|---|---|
| `.venv-npu`（aidlite 所在的系统解释器 + `--system-site-packages`） | 工程版本门槛挡住，装不进工程 |
| 侧车（主进程 + NPU 子进程 IPC） | 需自写 IPC 层 |
| **自建绑定（本目录）** | 需随 aidlite-sdk 升级重编 |

## 它是什么（不是 Python 扩展模块）

```
aidlite.hpp ──(g++)──> libaidlite_cabi.so     extern "C" 外壳（~150 行）
                              │ ctypes（运行期绑定，只依赖普通共享库 C ABI）
                              ▼
                  aidlite/__init__.py          ctypes 门面（~375 行，API 形状对齐官方绑定）
```

| | 官方 `soaidlitesdk` | 本项目 `libaidlite_cabi.so` |
|---|---|---|
| `PyInit_*` 入口 / Python C-API 符号 | 有 / 141 个 | 无 / 0 个 |
| 加载方式 | CPython `import` 机制 | `ctypes.CDLL()`（`import` 机制不参与） |
| 文件名后缀要求 | 必须 `.cpython-3xx-…so` | 任意 |
| 与 Python 版本的耦合 | **锁死** | **无** |
| 编译需要 | Python 头文件 + pybind11 | 只 `g++`（**不需要 `python3-dev`**） |
| 类型转换 | pybind11 自动 | 手写（即那 375 行门面） |

`is_native=false` 是对齐官方语义的关键：输入/输出交给 aidlite 按模型自带量化参数做量化/反量化。

## 用法

```bash
cd ~/projects/DonkeyDrift
bash scripts/aidlite_cabi/rebuild.sh              # 默认装进 .venv；也可传 .venv-npu 等
.venv/bin/python -c "import aidlite; print(aidlite.get_library_version())"
```

脚本是**探测式且幂等**的：官方绑定可用 → 直接跳过；缺头文件/库/g++ → 给准确修复命令；
重复运行 = 重编重装（升级 aidlite-sdk 后正是需要跑一次）。

## 换设备/新环境需要什么（依赖不在仓库里）

| 需要 | 来源 | 说明 |
|---|---|---|
| `aidlite.hpp` + `libaidlite.so` | **`aidlite-sdk`**（`sudo aid-pkg install aidlite-sdk`） | 编译本绑定的唯一依赖 |
| `libaidlite_qnn240.so` | `aidlite-qnn240` | QNN240 模型必须；`sudo aid-pkg install aidlite-qnn240 --without-progress` |
| `qairt/qnn240/*`（QNN 运行时） | `aidlux-aistack-base` | 随上一步级联安装 |
| `g++` | `sudo apt-get install -y g++` | **只需 g++**（ctypes 路线，不需要 python3-dev） |
| 设备已激活 license | 镜像自带 | 日志会打 license ID |
| DSP/RPC 通道 | 镜像自带 | `/dev/fastrpc-*` 或老式 `/dev/adsprpc-smd` **都可能**，别写死节点名 |

`libaidlite_cabi.so` **不入库**（按本机头文件/库编出的产物，换设备必重编）—— 克隆后跑一次 `rebuild.sh` 即可。

## 实测（QCS6490 + aidlite 2.5.1.304 + DKG-1 `.aidem`）

| 项目 | 结果 |
|---|---|
| 3.12 `import aidlite` | ✅ `aidlite-cabi-0.1` / C 库 `Aidlux_Aidlite_C4L_V2.5.1.304` |
| `init()` / `load_model()` | ✅ `0` / `0` |
| 直调 aidlite 推理 | **0.88 ms/次**（20 次平均） |
| 工程 `NpuLinearPilot` 路径 | `load()` 0.60 s、**1.68 ms/次**（100 次，含 pilot 归一化） |
| 与 3.10 官方绑定对比 | **逐位一致** `[0.0, -0.062795]` |
| 授权 | 不受影响（license 校验在 `libaidlite.so` 内，已激活） |

## 已知边界

- 只实现调用方用到的子集：`Context / TensorInfo / DeviceInfo / get_set_*_tensor_buffer` 未实现；
  官方 `aidlite` 包的其余成员（见 `dir(soaidlitesdk)`）同样未覆盖
- **aidlite 的 TFLite/CPU 后端**经此门面 `init()` 返回 1（日志取不到）—— 有 TF 的解释器里
  `tflite_linear` 走原生 TF 路径，此路未被使用；若要在无 TF 环境跑 `.tflite` 需另查
- 门面装在 **venv 的 site-packages 里**（不在仓库内）→ 新建 venv 后重跑 `rebuild.sh`
- **aidlite-sdk 升级后必须重跑**（外壳按 `aidlite.hpp` 的签名与 `Config` 字段布局编译）
- 官方若开始提供匹配 ABI 的绑定，应改回官方绑定（零维护）
