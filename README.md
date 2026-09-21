# 3DGS Point Cloud Render

面向 PLY 文件的点云处理与静态可视化工具，提供属性保留式去噪、纯点云渲染和 3D Gaussian Splatting 渲染。通过统一命令 `plyscene` 使用，不依赖仿真器、特定场景或数据集。

## 功能

| 功能 | 说明 | 运行条件 |
|---|---|---|
| 文件检查 | 查看点数和属性；可选扫描 XYZ 范围 | CPU |
| 去噪 | Radius、Statistical Outlier Removal（SOR）或两者组合，保留幸存点的全部属性 | CPU |
| 点云渲染 | 正交投影、不透明圆点、深度遮挡和超采样抗锯齿 | CPU |
| Gaussian 渲染 | 基于尺度、四元数和透明度的各向异性 Gaussian 合成 | NVIDIA GPU、CUDA、PyTorch、gsplat |
| 轨迹路径图 | 已对齐 XYZ 轨迹、自动局部裁切、近侧剖切、三维切线视锥；支持两个后端 | 取决于渲染后端 |
| 批量渲染 | 按清单逐个输出独立图片和报告 | 取决于渲染后端 |

两个渲染后端均提供可调整的质量参数和可选软阴影。**未提供轨迹时，默认使用全部有效点、无额外裁剪、无透明度阈值，并关闭合成阴影。** 输出为无损 PNG，不提供拼图、视频、交互式查看器、模型训练或点云到 Gaussian 的重建。

当前版本为 **0.1.0**。Gaussian 后端保留并使用各向异性形状与透明度，但目前只计算 DC 颜色，不计算高阶球谐（SH）的视角相关颜色。

## 安装

### 基础功能

要求 Python 3.10 或更高版本。以下示例使用 Bash，在 Linux/macOS 上从源码安装：

```bash
git clone https://github.com/lemonoscar/3dgs-pointcloud-render.git
cd 3dgs-pointcloud-render

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

plyscene --help
```

基础依赖为 NumPy、SciPy 和 Pillow；检查、去噪和点云渲染不需要 GPU。本文后续命令从仓库根目录执行，也可以使用输入和配置文件的绝对路径。`configs/` 随源码提供，不作为配置资源安装到 Python 包内。

### Gaussian 后端（可选）

先安装与目标机器驱动和 CUDA 环境匹配的 CUDA 版 PyTorch，再安装可选依赖：

```bash
python -m pip install -e '.[gaussian]'
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

最后一项应为 `True`。本项目固定使用 `gsplat==1.5.3`，首次运行可能需要编译扩展，需准备匹配的 CUDA Toolkit 和编译工具链。安装成功或检测到 GPU，不代表实际渲染已通过验证。

## 输入格式

支持 **binary_little_endian 1.0** 格式的 PLY，要求只包含一个非空 `vertex` 元素，所有属性均为标量。ASCII、大端、包含面或 `list` 属性的文件不受支持，需要先转换为符合要求的点云 PLY。

| 输入类型 | 必需属性 | 可用操作 |
|---|---|---|
| XYZ 点云 | `x`、`y`、`z` | 检查、去噪、灰色点云渲染 |
| 彩色点云 | XYZ 和 `red`、`green`、`blue` | 检查、去噪、彩色点云渲染 |
| Gaussian PLY | XYZ、`scale_0…2`、`rot_0…3`、`opacity`、`f_dc_0…2` | 检查、去噪、点云渲染、Gaussian 渲染 |

Gaussian 属性必须采用本项目支持的存储约定：自然对数尺度、`wxyz` 四元数、logit 透明度和 DC 球谐颜色。**普通 XYZRGB 点云不能仅通过切换后端变成训练好的 Gaussian 模型。**

坐标单位沿用原文件，不自动识别米、厘米或毫米。默认展示向上轴为 Z，可通过 `rotate_x` 调整展示旋转。完整约定见 [数据格式与参数说明](docs/data_format.md)。

## 快速开始

以下用 `data/input.ply` 举例，请替换为自己的文件路径。去噪是可选步骤；已有合适输入时可以直接渲染。

### 1. 检查文件

```bash
# 检查文件头、数据长度、点数和属性
plyscene inspect data/input.ply

# 额外扫描 XYZ，报告有限坐标的点数和范围
plyscene inspect data/input.ply --scan
```

`gaussian: true` 仅表示必需字段存在，不代表数值、属性存储约定或 GPU 环境已验证。`--scan` 检查 XYZ，不检查所有 Gaussian 属性。

### 2. 去噪

```bash
plyscene denoise data/input.ply \
  --config configs/denoise_default.json \
  --output outputs/clean.ply
```

生成 `outputs/clean.ply` 和 `outputs/clean.json`。只删除被筛除的点，保留幸存点的属性名、类型、数值、顺序和坐标。不修改原文件，不自动裁剪，不调整 Gaussian 尺度或四元数。

默认配置为体素辅助 Radius + SOR。参数取决于输入单位和点密度，应检查输出后再决定是否用于最终展示。

### 3. 渲染点云

```bash
plyscene render outputs/clean.ply \
  --backend points \
  --output outputs/points.png
```

默认满质量设置：全部筛选后有效点、2400 × 1800 输出、2× 超采样，即在 4800 × 3600 内部分辨率渲染后下采样。没有 RGB 属性时使用 Gaussian DC 颜色；两者均没有时使用灰色。

### 4. 渲染 Gaussian

要求输入具有有效 Gaussian 属性，并已安装可选 GPU 依赖：

```bash
plyscene render data/gaussian.ply \
  --backend gaussian \
  --output outputs/gaussian.png
```

也可以输入经过本工具去噪、仍保留完整 Gaussian 属性的 PLY。默认质量与点云后端相同，不限制 Gaussian 数量。

### 5. 按已有轨迹绘制路径图

```bash
plyscene render data/input.ply \
  --trajectory data/route.csv \
  --route-config configs/route_default.json \
  --output outputs/route.png
```

CSV 带 `x,y,z` 表头，坐标和单位必须与 PLY 一致。工具自动沿路线裁切，降低近侧遮挡，默认45°俯视；视锥尖端严格在线上，方向来自三维路径切线，不代表实测相机姿态。默认点云，也可指定 `--backend gaussian`；不寻找路线或自动配准。

同时生成 PNG、保留全部属性的 `.crop.ply`、规范化 `.trajectory.csv` 和 JSON 报告。取景、线宽和视锥大小可配置。参见 [完整绘制方法](docs/trajectory_rendering.md) 和 [瀛洲园三个示例](examples/yingzhouyuan/README.md)。

### 执行前预检

`denoise`、`render` 和 `batch` 都支持 `--plan`。在命令末尾添加该参数，只检查文件头、相关配置、提供的轨迹内容和输出冲突，不执行去噪或渲染，不创建输出。

`--plan` 不扫描全部属性、不加载 CUDA、不估计内存或显存是否充足；实际执行仍可能遇到数据数值、依赖或资源错误。

## 渲染质量接口

点云和 Gaussian 后端共用以下可修改接口：

| 参数 | 默认满质量 | 说明 |
|---|---|---|
| `--quality` | `full` 对应的默认设置 | 可选 `full`、`preview`；显式传入会覆盖配置文件的分辨率和采样设置 |
| `--width` / `--height` | `2400` / `1800` | 最终图像宽高，单位像素 |
| `--ssaa` | `2` | 内部宽高分别放大的倍数 |
| `--max-points` | `0` | `0` 使用全部筛选后有效点或 Gaussian；正整数显式限制数量 |
| `--point-radius` | `1` | 仅点云后端：圆盘半径，单位为最终图像像素 |
| `--tile` | `1024` | 仅 Gaussian 后端：分块边长，单位为内部渲染像素，不是点数限制 |

“满质量”表示默认不做降采样、不因资源不足而静默降低质量，**不是固定的最高分辨率，也不是高阶 SH 着色承诺**。可以继续提高分辨率和超采样；增加像素不会恢复输入中不存在的细节。

`preview` 预设使用 1200 × 900、`ssaa=1` 和最多 500,000 个筛选后有效点。以下示例适用于两个后端，只需修改 `--backend`：

```bash
# 快速预览
plyscene render data/input.ply --backend points \
  --quality preview --output outputs/preview.png

# 满质量，并进一步提高分辨率与超采样
plyscene render data/input.ply --backend points \
  --quality full --width 3200 --height 2400 --ssaa 3 \
  --output outputs/high_resolution.png

# Gaussian：全量渲染，修改内部块大小
plyscene render data/gaussian.ply --backend gaussian \
  --quality full --tile 512 --output outputs/gaussian_full.png
```

`--quality full` 会重设宽高、超采样和点数上限，不会取消显式配置的裁剪范围或透明度阈值。所有实际参数和最终渲染点数均写入输出报告。

## 可选软阴影

两个后端默认关闭阴影；使用以下选项控制：

```bash
# 开启软阴影，默认强度 0.24
plyscene render data/input.ply --backend points \
  --shadow --output outputs/points_shadow.png

# 自定义强度，范围 [0,1]
plyscene render data/gaussian.ply --backend gaussian \
  --shadow 0.2 --output outputs/gaussian_shadow.png

# 强制关闭，包括覆盖配置文件中的阴影设置
plyscene render data/input.ply --backend points \
  --no-shadow --output outputs/points_no_shadow.png
```

`--shadow` 和 `--no-shadow` 不能同时使用。`--shadow 0` 也表示关闭。

阴影由点中心投影到展示坐标下的地面，经过轮廓膨胀和模糊得到，是**合成展示效果**，不是物理光照、光线追踪或真实环境遮挡。开启阴影不会修改输入几何。

## 配置文件

`--config` 接受 JSON 对象。可以提供完整配置，也可以只写需覆盖的项。未知参数会报错；未提供项继承代码默认值，不继承上一次运行。

渲染配置示例：

```json
{
  "width": 3200,
  "height": 2400,
  "ssaa": 2,
  "max_points": 0,
  "azimuth": -45,
  "elevation": 50,
  "rotate_x": 0,
  "shadow": 0.24,
  "min_opacity": 0,
  "bounds": null
}
```

保存为 `render.json` 后使用：

```bash
plyscene render data/input.ply --backend points \
  --config render.json --output outputs/custom.png
```

`azimuth` 是相机水平朝向，`elevation` 是俯视角，单位均为度；`rotate_x` 是显示旋转，不改写数据。`bounds` 始终使用源 PLY 坐标，格式为 `[xmin,ymin,zmin,xmax,ymax,zmax]`。非零 `min_opacity` 要求存在 Gaussian logit `opacity` 字段。

仓库提供 [点云配置](configs/points_hq.json)、[Gaussian 配置](configs/gaussian_hq.json) 和 [去噪配置](configs/denoise_default.json)。质量预设只通过 CLI 的 `--quality` 选择；JSON 中直接设置对应数值，不使用 `quality` 字段。

### 去噪参数

| 参数 | 默认值 | 含义 |
|---|---|---|
| `mode` | `"voxel"` | `voxel`：体素辅助；`exact`：原始点邻域 |
| `method` | `"both"` | `radius`、`sor` 或 `both` |
| `voxel` | `0.08` | 体素边长，单位与输入一致，仅用于体素模式 |
| `radius` | `0.24` | Radius 查询半径，单位与输入一致 |
| `min_neighbors` | `5` | Radius 所需最少邻居数，不计自身 |
| `sor_k` | `20` | SOR 邻居数，不计自身 |
| `sor_std_ratio` | `2.0` | SOR 阈值的标准差倍数 |
| `workers` | `4` | 邻域查询工作线程数 |

体素模式以每个非空体素内的平均点位置作为代表点，判断后保留通过筛选的体素中的全部原始记录。输出不是降采样后的代表点；这种近似方式也可能保留好体素内的少量噪声。

`both` 在同一代表点集上分别判断 Radius 和 SOR，取保留集合的交集，不是依次重建邻域执行两个过滤器。精确模式直接在原始点上判断，通常需要更多资源。邻域算法不理解物体语义，可能误删稀疏结构，需要结合实际尺度和密度调整参数。

## 批量独立出图

批量操作不限制场景数量，不要求特定文件名，也不生成拼图。将下面的清单保存为 `scenes.json`：

```json
{
  "schema_version": 1,
  "scenes": [
    {
      "id": "scene_a",
      "input": "scene_a.ply",
      "render": {"rotate_x": 0, "azimuth": -45}
    },
    {
      "id": "scene_b",
      "input": "scene_b.ply",
      "render": {"rotate_x": 90, "azimuth": -45}
    }
  ]
}
```

`input` 相对于 `--data-root` 解析，必须位于该目录内；清单自身的位置不影响输入解析。`id` 必须唯一，建议只使用英文字母、数字、下划线和连字符。`render` 可省略；可选的 `expected_source_points` 用于核对文件点数，不等同于内容哈希校验。

```bash
# 先检查全部输入，不启动渲染
plyscene batch --manifest scenes.json --data-root data \
  --backend points --quality full --shadow \
  --output outputs/batch --plan

# 确认后执行：去掉 --plan
plyscene batch --manifest scenes.json --data-root data \
  --backend points --quality full --shadow \
  --output outputs/batch
```

每个场景输出 `<id>.png` 和 `<id>.json`。使用 `--scene scene_a` 只处理指定场景。批量 Gaussian 渲染改为 `--backend gaussian`，要求选中输入均符合 Gaussian 格式。

参数优先级从低到高为：

1. 代码默认值。
2. `--config` 文件。
3. 清单内单场景 `render` 设置。
4. 显式指定的 `--quality` 预设。
5. 显式指定的质量参数及阴影开关。

未传 `--quality` 时，不额外覆盖配置文件。批量流程先对所有选中输入进行预检，再顺序执行；不自动续跑或跳过已有输出。

## 输出、数据安全与性能

- 不覆盖输入文件。输出 PLY、PNG 或对应 JSON 已存在时拒绝执行，请选择新的输出路径。
- 报告记录输入/输出 SHA-256、实际配置、点数、依赖版本和可获取的 Git 状态。大文件哈希会增加磁盘读取时间。
- 中断可能留下不完整输出，程序不会自动删除这些文件。
- 两个渲染后端统一按“浮点属性有限性检查 → 可选透明度过滤 → 可选 bounds 裁剪 → 可选轨迹裁切 → 可选均匀索引采样”选择点。“全量”指通过检查和显式过滤后的全部点。
- 全量点云和高倍超采样具有较高内存开销。Gaussian 的分块仅减少部分光栅化中间开销，所有 Gaussian 参数仍需放入显存。
- 点云、模型、缓存和生成图片应保留在 Git 之外。仓库提供排除规则和 CI 文件检查，不应使用强制添加绕过限制。

本项目不附带点云数据。请自行准备输入，并确认访问、处理和再分发权限。

## 项目结构

```text
src/plyscene/
  cli.py                  # 命令入口、配置和处理流程
  ply_io.py               # PLY 检查与属性保留式读写
  denoise.py              # Radius / SOR
  transforms.py           # 展示坐标变换
  camera.py               # 共享相机和质量预设
  render_points.py        # CPU 点云渲染
  render_gaussian.py      # CUDA Gaussian 渲染
  trajectory.py           # 轨迹校验、局部裁切、三维切线视锥与标注
  compose.py              # 背景、可选软阴影与最终图像合成
configs/                  # 通用预设和可选数据集清单
examples/yingzhouyuan/     # 三条示意轨迹与配置，不含场景资产
tests/                    # 临时合成数据测试
docs/                     # 数据格式与补充说明
.github/workflows/        # CPU 测试和入库文件检查
```

数据集专用配置不是通用运行前提，处理自己的文件无需准备任何特定目录或历史结果。

## 测试与验证范围

```bash
python -m unittest discover -s tests -v
git diff --check
```

测试在临时目录生成小型 PLY，覆盖属性保留、去噪、点选择、相机、遮挡、CLI、质量覆盖、阴影开关、批量独立出图和禁止覆盖。测试不需要真实场景文件。

21项 CPU 测试覆盖原有流程与轨迹几何、局部高度裁切、三维视锥对齐、属性保留和输出保护。瀛洲园扩展路线已完成实际点云与 Gaussian GPU 渲染，两者裁切指纹及相机一致，详见 [实图验证记录](docs/trajectory_validation.md)。跨平台、全新 CUDA 安装和八场景批量仍需单独验证。

## 常见问题

**场景朝向不合适。** 检查输入向上轴，通过配置中的 `rotate_x`、`azimuth` 和 `elevation` 调整。程序不自动推断场景方向。

**使用 full 后点数仍比原文件少。** 查看报告中的各阶段点数；无效浮点属性和显式裁剪/透明度阈值仍会生效。去噪输出本身也已少于原始输入。

**普通点云无法使用 Gaussian 后端。** 检查必需字段和存储约定；本工具不提供从 XYZRGB 重建 Gaussian 参数的功能。

**内存或显存不足。** 使用 `--quality preview` 检查效果，或显式降低分辨率、超采样及点数上限。默认不会自动牺牲质量以适配资源。

**去噪删除了稀疏表面。** 半径和体素大小不是通用常量，应按数据单位和密度调整；也可降低最少邻居数或放宽 SOR 阈值后比较结果。

## 许可

本项目采用 [MIT License](LICENSE)。第三方依赖遵循各自许可证；MIT 许可不授予输入点云或其他外部数据的使用权，数据许可由其权利人决定。
