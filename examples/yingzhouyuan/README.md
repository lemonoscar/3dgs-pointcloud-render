# 瀛洲园轨迹示例

三个示例使用同一个**原始** `visual_ply/yingzhouyuan.ply`，Z-up，单位沿用原资产。场景文件不随仓库分发。它有13,860,573个 Gaussian 记录，SHA-256：

```text
590cc85ae907be202433612941925fa0a34a95da36b6ad98826e658dc59b070b
```

这些 CSV 是为展示手工整理的示意轨迹，不是机器人实测日志，不保证碰撞可行。视锥由三维路径切线生成，不是实测相机姿态。路线位置已经包含绘图所需的离地高度，`floor_offset=0.1` 只用于解释局部地面，不再抬高路线。

| 案例 | CSV | 行数 | 路径配置 | 内容 |
|---|---|---:|---|---|
| 室内 | `indoor.csv` | 100 | `route.json` | 厨房室内转弯路线 |
| 台阶 | `steps.csv` | 230 | `route.json` | 客厅走向门口两级台阶，进入较高的灰色地面区域 |
| 扩展 | `extended.csv` | 465 | `extended.route.json` | 从前一终点继续转弯，走到楼梯，上第一段楼梯到中间平台 |

扩展路线未覆盖折返后的上层楼梯和完整二楼。其较低的 `far_height=1.05` 减少高处无关结构，较小的 `framing=0.73` 拉远取景。两种参数都能按新场景修改，不属于程序硬编码。

## 复现

从仓库根目录运行，先安装本仓库。将变量替换成你自己的原始文件位置：

```bash
SCENE=/path/to/visual_ply/yingzhouyuan.ply

plyscene render "$SCENE" --trajectory examples/yingzhouyuan/indoor.csv \
  --config examples/yingzhouyuan/indoor.render.json \
  --route-config examples/yingzhouyuan/route.json \
  --output outputs/yingzhouyuan_indoor.png

plyscene render "$SCENE" --trajectory examples/yingzhouyuan/steps.csv \
  --config examples/yingzhouyuan/steps.render.json \
  --route-config examples/yingzhouyuan/route.json \
  --output outputs/yingzhouyuan_steps.png

plyscene render "$SCENE" --trajectory examples/yingzhouyuan/extended.csv \
  --config examples/yingzhouyuan/extended.render.json \
  --route-config examples/yingzhouyuan/extended.route.json \
  --output outputs/yingzhouyuan_extended.png

# 相同取景、裁切和标注，改用 Gaussian；需 CUDA 和可选依赖
plyscene render "$SCENE" --trajectory examples/yingzhouyuan/extended.csv \
  --config examples/yingzhouyuan/extended.render.json \
  --route-config examples/yingzhouyuan/extended.route.json \
  --backend gaussian --output outputs/yingzhouyuan_extended_gaussian.png
```

加 `--plan` 可先做预检；输出已存在时换一个名字。示例开启0.24合成阴影，但没有点云柔化或景深。`min_opacity=0.1` 是本资产的选择；用于普通 XYZRGB 点云时需设为0。

## 历史坐标转换

`indoor.csv` 来自旧清理版本中的厨房轨迹，现已还原到原始 PLY 坐标。旧 `denoised_ply_v3/yingzhouyuan.ply` 曾绕 XY 枢轴 `(4.649747848510742, 4.896892547607422)` 旋转180°；还原公式为 `raw.xy = 2*pivot - old.xy`，Z不变。不能绕世界原点简单取负，也不能将本 CSV 直接叠到该旧旋转版本。

`steps.csv` 与 `extended.csv` 本来就在原始坐标系。CSV 保留双精度写出精度，避免把原本共线的密集采样变成微小折线，影响裁切加速。通用工具不自动识别或应用这些历史变换。

换场景时替换 PLY、CSV，并按单位、地面高度、相机朝向和显示范围调节配置。完整方法见 [轨迹绘制方法](../../docs/trajectory_rendering.md)，真实双后端结果见 [验证记录](../../docs/trajectory_validation.md)。
