# 数据与参数约定（0.1）

## PLY

仅支持 binary_little_endian 1.0、单个非空 vertex element、标量属性。类型支持 char/uchar/short/ushort/int/uint/float/double 及对应 int8…float64 别名。文件体长度必须精确对应声明的点数和属性，额外元素不会被忽略。

XYZ 为必需字段。纯点云颜色优先 `red/green/blue`：整数按各字段类型最大值归一化，浮点应为 [0,1]；否则使用 `.5 + 0.28209479177387814 * f_dc_i`；没有颜色时使用灰色。

Gaussian 后端要求标准 3DGS 存储约定：

| 字段 | 含义 |
|---|---|
| x/y/z | 中心坐标 |
| scale_0…2 | 自然对数尺度，渲染时 exp |
| rot_0…3 | wxyz 四元数，渲染时归一化，不允许零四元数 |
| opacity | logit 透明度，渲染时 sigmoid |
| f_dc_0…2 | DC 颜色 |
| f_rest_* | 保留，但本版不做高阶 SH 着色 |

同名字段采用线性尺度、xyzw 或直接 alpha 的其他格式不能直接套用。不能从普通点云恢复训练好的 Gaussian 参数。

## 属性与筛选

去噪只删除整条 vertex record，保持所有属性名、类型、数值、原始点顺序和坐标，不修改 Gaussian 尺度/旋转。去噪仅按 XYZ 有限性和邻域筛选；其他属性不合法时仍保留原值，由后续渲染检查处理。

两种渲染共享选择顺序：所有浮点属性有限 → 可选 opacity 阈值 → 可选 source-coordinate bounds → 可选均匀索引采样。非有限属性属于无效数据检查，不属于空间去噪。默认不设 opacity 阈值、不裁剪、不采样。

报告区分文件总点数、有限点数、透明度过滤后点数、裁剪后点数和实际渲染点数。`max_points=0` 指所有幸存点，不是保留原始噪声；正数采样在筛选后执行。

## 坐标和相机

单位沿用 PLY。默认源坐标为 Z-up，通过 `rotate_x` 指定展示旋转；不推断朝向，不修改原文件。`bounds` 始终是原始 PLY 坐标下的 `[xmin,ymin,zmin,xmax,ymax,zmax]`，不是旋转后的坐标。

相机为正交投影。azimuth 单位度；elevation 为 (0,90]；内部使用源坐标相机变换，Gaussian 的四元数不需要因显示旋转重新写入。框选以点中心范围为依据，极大的 Gaussian 椭球仍可能延伸到图片外。

## 配置

未知顶层参数被拒绝。去噪参数见 `configs/denoise_default.json`，渲染见 `configs/points_hq.json` 与 `configs/gaussian_hq.json`；均为扁平 JSON 对象。

width/height/ssaa/tile 为正整数；point_radius、max_points 为非负整数；shadow 为 [0,1]；min_opacity 为 [0,1)，且非零时要求 opacity 字段。Gaussian 后端不使用 point_radius；点云后端不使用 tile。

两个后端默认使用 full 对应设置：2400×1800、ssaa=2、max_points=0，shadow=0。CLI 的 --quality full / preview 仅覆盖宽高、超采样和点数上限，不改变裁剪或透明度过滤。显式 --width、--height、--ssaa、--max-points、--point-radius 和 --tile 具有更高优先级。--shadow 不带数值时设置 0.24，带数值时设置指定强度；--no-shadow 设置为 0，两者互斥。

批量命令为 batch，只输出每个场景自己的 PNG 和 JSON，不生成拼图。配置优先级为代码默认值 → 通用配置文件 → 单场景配置 → 显式质量预设 → 显式数值参数/阴影选项。质量预设不是 JSON 配置字段。

输出 PLY/PNG 和同名 JSON 都不得已存在；中断时可能留下不完整输出，请检查后换一个输出路径，不会自动删除或覆盖旧文件。
