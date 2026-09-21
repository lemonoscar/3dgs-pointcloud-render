# 八场景与迁移记录

## 边界

新仓库是独立研究工具，不依赖旧 arm-vla 导入路径、Isaac Sim、旧 photo 报告或机器本地 `.deps`。旧工程和全部数据保持原位，不删除、不移动；新仓库仅维护代码和小型配置。回退时可继续使用原工程。

| 旧实现（相对旧 pointcloud_visualization） | 新位置 | 处理 |
|---|---|---|
| render_paper.py | render_points.py / camera.py / compose.py | 复用不透明圆点深度渲染和投影软阴影，提取共享相机 |
| gaussian_tool/clean_scenes.py | denoise.py / ply_io.py | 保留 Radius/SOR 思路与完整 record 筛选；移除按场景名硬编码的裁剪和旋转 |
| gaussian_tool/render_figure.py | render_gaussian.py | 保留 gsplat 分块正交渲染；移除旧绝对依赖路径 |
| render_recovered_v4.py | cli.py batch + configs/scenes_v4.json | 把旧报告中的输入、阈值、坐标范围显式固化，不再在运行时读取旧报告；只输出独立图片 |

这不是纯机械搬运：增加严格输入验证、输出防覆盖、统一筛选和参数优先级；因此不承诺新旧图像逐像素相等。旧模板的 Gaussian 高阶 SH 未评估，本版同样只用 DC。

## 八场景映射

`--data-root` 指向包含下表相对路径的目录。无需把数据搬进本仓库。

| 场景 | 相对路径 | 文件点数 |
|---|---|---:|
| guanlan | denoised_ply/guanlan.ply | 15,108,095 |
| huzhou | denoised_ply/huzhou.ply | 1,917,325 |
| liangzhu | denoised_ply/liangzhu.ply | 5,547,778 |
| qilou | denoised_ply_v2/qilou.ply | 2,709,487 |
| roppongi | denoised_ply_v4/roppongi.ply | 8,322,082 |
| tianxi | denoised_ply_v4/tianxi.ply | 15,633,415 |
| yingzhouyuan | denoised_ply_v3/yingzhouyuan.ply | 9,610,561 |
| yinluyuan | denoised_ply_v4/yinluyuan.ply | 16,555,518 |

旧目录 v1/v2/v3/v4 不是全八场景统一版本。部分 v4 修改仅缩小 Gaussian 屋顶区域的尺度，点中心没有变化，所以纯点云渲染不会复现这种 Gaussian 专属外观修改。

`scenes_v4.json` 保存源坐标裁剪范围和 opacity=0.1 等旧条件。`reference_gaussian_points` 仅是历史参考，不是新渲染结果：源坐标边界浮点运算与旧世界坐标转换存在几个点的差异；统一新选择规则后两个后端使用同一组点中心。

`scenes_clean_full.json` 使用同样的已清理文件，取消额外 bounds/opacity，不重复去噪。这才是“清理后文件的全量有效点”展示入口。

manifest 的点数校验用于发现明显选错文件，不能证明内容一致。每次实际输出会记录输入 SHA-256；首版没有为八个大文件预先做全文件校验，也没有把点数匹配误称为哈希验证。

## 验证与复现

```bash
python -m unittest discover -s tests -v
plyscene batch --manifest configs/scenes_v4.json \
  --data-root /path/to/pointcloud_visualization \
  --backend gaussian --config configs/gaussian_hq.json \
  --output outputs/v4_gaussian --plan
```

CPU 测试覆盖完整属性保留、Radius/SOR 三种方法、异常输入、先筛选后采样、相机投影一致性、遮挡、CLI、质量参数覆盖、阴影开关、批量独立出图、报告和禁止覆盖。合成数据在临时目录生成，测试结束清理，不在 Git 中存 PLY。

初版的 gallery 命令及拼图功能已移除，批量独立出图改用 batch。两个后端默认全量、2400×1800、2× 超采样，阴影默认关闭；可用 --quality、分辨率参数和 --shadow / --no-shadow 显式控制。此接口调整尚未发布，不影响原工程中的历史脚本或数据。

后续实图验收顺序：先一个小场景（例如 huzhou）点云图 → 同一输入 Gaussian 图 → 确认朝向和阴影 → 八场景完整批量。此阶段需额外验证 GPU 环境、显存峰值、Gaussian 分块接缝与真实视觉效果。首版未执行这些昂贵验证。

当前版本使用可安装依赖范围而非完全锁定环境。输出记录实际依赖版本；正式发布图像时还应单独保存 `python -m pip freeze`、GPU/驱动信息和实际命令，保存在外部结果目录。只有完成实图回归后再建立不可变 release/tag；源码推送不代表实图回归或发布验收完成。

## 2026-09-21：通用轨迹功能整理

旧 `render_indoor_pointcloud_route_v9.py`、`render_indoor_gaussian_route_v8.py`、`render_indoor_steps_route.py` 和 `render_indoor_steps_extended.py` 的路线标注需求归入 `src/plyscene/trajectory.py` 与 `render --trajectory`，三个案例转为 `examples/yingzhouyuan/` 下的小型 CSV/JSON。旧脚本、手工裁切版本和大文件保留原位。

这里使用原始 `visual_ply/yingzhouyuan.ply`（13,860,573点），与上表的旋转、去噪版本不同，不能直接混用轨迹。通用实现没有加入按场景名称判断的逻辑、手工删柱区域或本地依赖路径。后端共用正交相机，因此不承诺复刻旧透视图片。

扩展路线已完成真实点云与 Gaussian 渲染，并核对相同裁切和取景；详见 [验证记录](trajectory_validation.md)。该结果不等于八场景全量批量或全新 GPU 环境安装通过。复现命令及原始坐标说明见 [示例](../examples/yingzhouyuan/README.md)。
