# 电力无人机三维航线规划与智能巡检系统：后端接口设计

版本：1.0.0-design。日期：2026-11-05。本文与 `power-inspection-openapi.json` 配套，是可供前后端联调实施的设计契约，尚未实现或部署。

## 1. 范围与技术栈

首版范围为单架多旋翼、静态三维场景、离线规划、轨迹回放、巡检照片识别和人工复核。不包含实机飞控下发、动态避障、多机协同或在线训练平台。

建议实现：Python + FastAPI + Pydantic + Uvicorn；SQLAlchemy + Alembic + SQLite；NumPy/SciPy 实现三维栅格 A* 和最近邻 + 2-opt；PyTorch + Ultralytics YOLO + OpenCV；本地文件存储。耗时规划与推理运行在独立工作进程，API 保存作业状态，前端轮询。多人并发部署再换 PostgreSQL。离线训练生成受信任权重，普通用户不上传和加载任意可执行模型。

## 2. 通用约定

- 基础路径：`/api/v1`。JSON 为 UTF-8；字段名采用 snake_case，ID 为字符串。时间为含时区的 RFC 3339，例如 `2026-11-05T10:30:00+08:00`。
- 成功：`{"data": {...}, "request_id": "req_001"}`。列表：`data.items`、`data.next_cursor`、`data.has_more`。分页参数 `cursor` + `limit`（默认 20，最大 100）；推荐稳定排序为创建时间和 ID；不提供前端自行推算的页码。二进制下载接口不包 JSON。
- 错误：`{"error":{"code":"STALE_SNAPSHOT","message":"场景已更新，请重新规划","details":[]},"request_id":"req_001"}`。服务端返回 `X-Request-ID`，允许客户端提供同名追踪标识并经服务端校验。
- 鉴权为扩展模块，但契约统一预留 `Authorization: Bearer <token>`。单人演示可由开发配置映射本地固定用户；不应把生产接口直接设为匿名。planner 修改任务和路线，reviewer 复核，admin 管理用户和模型；文件权限继承所属业务资源。
- `GET` 可编辑资源返回强 `ETag`；修改和删除要求 `If-Match`。例如 `If-Match: "route_001:3"`。缺失为 428，不匹配为 412；业务状态冲突为 409。所有 PATCH 请求模型均设置 `minProperties: 1`，空对象不可提交。复核使用对应 Detection 的 ETag；复核响应后可重新 GET 获取新 ETag。
- 异步创建返回 HTTP 202、`JobAccepted` 和 `Location: /api/v1/jobs/{job_id}`，建议轮询间隔由 `Retry-After` 指示。`Idempotency-Key` 建议用于重复提交；相同用户、键、请求体在 24 小时内返回同一作业，不同请求体返回 409。取消作业返回当前 Job，可先为 `cancel_requested`。
- 文件先通过 multipart `/files` 上传，再用 `file_id` 引用。建议首版单个图片上限 20 MB、模型/几何 200 MB；校验真实媒体类型、路径和扩展名。图片 JPG/PNG，模型 GLB/glTF，几何 JSON。glTF 外部资源需作为受控资产包处理，不任意抓取外部 URL。扩展的 trusted_weights 仅管理员使用、限制来源及格式，部署配置明确开启后才能接受，不允许普通用户上传任意权重；首版权重随受信任离线部署流程安装。文件接口需要权限校验，不能暴露服务器磁盘路径。

## 3. 坐标、快照和版本

`Scene.origin_wgs84` 固定场景原点，采用 WGS84 经纬度和椭球高；业务三维位置统一为局部 ENU（x 东、y 北、z 天），单位米。首版高程基准固定 `WGS84_ELLIPSOID`，不能把海拔、相对地面高度和椭球高混用。场景原点创建后不可直接修改；迁移坐标需整体转换数据并建立新场景。

需要区分三种实体：**Target（拍什么）**、**Viewpoint（在哪里拍、相机朝哪里）**、**Waypoint（路线经过哪里，可能仅用于绕障）**。相机 heading 北为 0°、顺时针，pitch 水平为 0°、向下为负。显示模型不能代替障碍物几何。

场景有资源 `revision` 与计算几何 `geometry_revision`。障碍物增删改、杆塔位置、替换场景几何模型等影响空间计算的操作必须增加 geometry_revision；只改名字不需要。巡检目标位置、拍摄要求修改增加目标 revision。任务创建/修改时保存场景几何和目标版本快照。

每次修改航点创建新 Route revision；旧版本保留不变。ValidationResult 绑定 route_revision、scene_geometry_revision 和对应任务快照。源数据变化立即把当前可复用性标记 stale，不能继续显示为可执行/校验通过；未归档任务回 draft。已 completed 的任务保持归档状态及历史快照，仅 Task.snapshot_status 变为 stale；原始校验 recorded_status 保留，ValidationResult.status 反映相对当前场景是否过期。异步作业即使算完旧快照，也不能自动激活过期航线。GET 端应按当前依赖重新判断有效性，不能只相信缓存状态。

完整路线校验需要检查机体扫掠体与整条航段，包括线段穿越和配置的隔离范围。路径简化/平滑后重检。覆盖率按视场、遮挡、目标像素尺寸、要求的不同视角数量计算；途经目标附近不等于拍摄覆盖。耗时包含飞行、爬升、悬停、返航和返航余量。参数约束由服务端校验，不由浏览器单独决定。

## 4. 接口清单

除“扩展”外均为首版接口；其中 UI 可分阶段完成。

### 鉴权与用户

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/login` | 登录获取访问令牌 | `LoginRequest` | `Token` / 200 | 扩展 |
| GET | `/api/v1/auth/me` | 查询当前用户 | `—` | `User` / 200 | 扩展 |
| GET | `/api/v1/users` | 分页查询用户 | `—` | `User` / 200 | 扩展 |
| POST | `/api/v1/users` | 创建用户 | `UserCreate` | `User` / 201 | 扩展 |
| PATCH | `/api/v1/users/{user_id}` | 修改角色或启用状态 | `UserPatch` | `User` / 200 | 扩展 |

### 文件

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| POST | `/api/v1/files` | 上传模型图片或几何文件 | `FileUpload` | `StoredFile` / 201 | 首版 |
| GET | `/api/v1/files/{file_id}` | 读取文件元数据 | `—` | `StoredFile` / 200 | 首版 |
| GET | `/api/v1/files/{file_id}/content` | 下载原文件内容 | `—` | `StoredFile` / 200 | 首版 |
| POST | `/api/v1/import-jobs` | 异步预检或批量导入资产 | `ImportJobRequest` | `JobAccepted` / 202 | 扩展 |
| GET | `/api/v1/import-jobs/{job_id}/items` | 分页读取批量导入逐行校验结果 | `—` | `ImportRowResult` / 200 | 扩展 |

### 三维场景

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/scenes` | 分页查询场景 | `—` | `Scene` / 200 | 首版 |
| POST | `/api/v1/scenes` | 创建带坐标基准的场景 | `SceneCreate` | `Scene` / 201 | 首版 |
| GET | `/api/v1/scenes/{scene_id}` | 读取场景和当前几何版本 | `—` | `Scene` / 200 | 首版 |
| PATCH | `/api/v1/scenes/{scene_id}` | 更新场景描述或模型文件 | `ScenePatch` | `Scene` / 200 | 首版 |
| GET | `/api/v1/scenes/{scene_id}/obstacles` | 分页查询障碍物 | `—` | `Obstacle` / 200 | 首版 |
| POST | `/api/v1/scenes/{scene_id}/obstacles` | 新增计算障碍物 | `ObstacleCreate` | `Obstacle` / 201 | 首版 |
| PATCH | `/api/v1/obstacles/{obstacle_id}` | 修改障碍物和隔离范围 | `ObstaclePatch` | `Obstacle` / 200 | 首版 |
| DELETE | `/api/v1/obstacles/{obstacle_id}` | 删除计算障碍物 | `—` | `EmptyResult` / 200 | 首版 |

### 线路与设备

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/lines` | 分页查询线路 | `—` | `Line` / 200 | 首版 |
| POST | `/api/v1/lines` | 新增线路 | `LineCreate` | `Line` / 201 | 首版 |
| GET | `/api/v1/lines/{line_id}` | 读取线路详情 | `—` | `Line` / 200 | 首版 |
| PATCH | `/api/v1/lines/{line_id}` | 修改线路属性 | `LinePatch` | `Line` / 200 | 首版 |
| GET | `/api/v1/towers` | 分页查询杆塔 | `—` | `Tower` / 200 | 首版 |
| POST | `/api/v1/towers` | 新增杆塔 | `TowerCreate` | `Tower` / 201 | 首版 |
| GET | `/api/v1/towers/{tower_id}` | 读取杆塔详情 | `—` | `Tower` / 200 | 首版 |
| PATCH | `/api/v1/towers/{tower_id}` | 修改杆塔属性或位置 | `TowerPatch` | `Tower` / 200 | 首版 |

### 巡检目标

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/targets` | 分页查询巡检目标 | `—` | `Target` / 200 | 首版 |
| POST | `/api/v1/targets` | 标记三维巡检目标 | `TargetCreate` | `Target` / 201 | 首版 |
| GET | `/api/v1/targets/{target_id}` | 读取目标与拍摄要求 | `—` | `Target` / 200 | 首版 |
| PATCH | `/api/v1/targets/{target_id}` | 修改目标位置或拍摄要求 | `TargetPatch` | `Target` / 200 | 首版 |
| DELETE | `/api/v1/targets/{target_id}` | 删除未被历史任务引用的目标 | `—` | `EmptyResult` / 200 | 首版 |

### 巡检任务

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/tasks` | 分页查询任务 | `—` | `Task` / 200 | 首版 |
| POST | `/api/v1/tasks` | 创建任务并冻结配置快照 | `TaskCreate` | `Task` / 201 | 首版 |
| GET | `/api/v1/tasks/{task_id}` | 读取任务和活动航线 | `—` | `Task` / 200 | 首版 |
| PATCH | `/api/v1/tasks/{task_id}` | 修改任务并生成新配置快照 | `TaskPatch` | `Task` / 200 | 首版 |
| POST | `/api/v1/tasks/{task_id}/complete` | 归档完成离线巡检任务 | `TaskCompleteRequest` | `Task` / 200 | 首版 |

### 规划与校验

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/tasks/{task_id}/viewpoints` | 分页查询候选拍摄点 | `—` | `Viewpoint` / 200 | 首版 |
| POST | `/api/v1/tasks/{task_id}/viewpoint-jobs` | 异步生成候选拍摄点 | `ViewpointJobRequest` | `JobAccepted` / 202 | 首版 |
| POST | `/api/v1/tasks/{task_id}/planning-jobs` | 异步生成避障巡检航线 | `PlanningJobRequest` | `JobAccepted` / 202 | 首版 |
| GET | `/api/v1/routes` | 分页查询任务航线 | `—` | `Route` / 200 | 首版 |
| GET | `/api/v1/routes/{route_id}` | 读取当前航线版本 | `—` | `Route` / 200 | 首版 |
| PATCH | `/api/v1/routes/{route_id}` | 保存编辑后的航点并创建新版本 | `RoutePatch` | `Route` / 200 | 首版 |
| GET | `/api/v1/routes/{route_id}/versions` | 分页查询航线历史版本 | `—` | `RouteVersion` / 200 | 首版 |
| GET | `/api/v1/routes/{route_id}/versions/{revision}` | 读取不可变航线历史快照 | `—` | `Route` / 200 | 首版 |
| POST | `/api/v1/routes/{route_id}/validation-jobs` | 异步校验整段路线与拍摄覆盖 | `ValidationJobRequest` | `JobAccepted` / 202 | 首版 |
| GET | `/api/v1/routes/{route_id}/validation` | 读取指定航线版本最新校验 | `—` | `ValidationResult` / 200 | 首版 |

### 仿真回放

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/routes/{route_id}/simulation` | 读取通过校验路线的仿真轨迹 | `—` | `Simulation` / 200 | 首版 |

### 计算作业

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/jobs` | 分页查询计算作业 | `—` | `Job` / 200 | 首版 |
| GET | `/api/v1/jobs/{job_id}` | 查询计算进度和结果资源 | `—` | `Job` / 200 | 首版 |
| POST | `/api/v1/jobs/{job_id}/cancel` | 请求协作取消计算 | `—` | `Job` / 202 | 首版 |

### AI巡检

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| POST | `/api/v1/photos` | 登记已上传巡检照片并关联设备 | `PhotoCreate` | `Photo` / 201 | 首版 |
| GET | `/api/v1/photos` | 分页查询巡检照片 | `—` | `Photo` / 200 | 首版 |
| GET | `/api/v1/photos/{photo_id}` | 读取照片及拍摄元数据 | `—` | `Photo` / 200 | 首版 |
| GET | `/api/v1/models` | 分页查询已部署AI模型 | `—` | `AIModel` / 200 | 首版 |
| GET | `/api/v1/models/{model_id}` | 读取模型版本和适用类别 | `—` | `AIModel` / 200 | 首版 |
| POST | `/api/v1/models` | 管理员登记受信任模型版本 | `AIModelRegister` | `AIModel` / 201 | 扩展 |
| POST | `/api/v1/inference-jobs` | 异步批量识别巡检图片 | `InferenceJobRequest` | `JobAccepted` / 202 | 首版 |
| GET | `/api/v1/inference-jobs/{job_id}/items` | 分页读取每张图片的处理状态 | `—` | `InferenceItemResult` / 200 | 首版 |
| GET | `/api/v1/detections` | 分页查询识别结果 | `—` | `Detection` / 200 | 首版 |
| GET | `/api/v1/detections/{detection_id}` | 读取单条识别结果 | `—` | `Detection` / 200 | 首版 |
| PUT | `/api/v1/detections/{detection_id}/review` | 确认驳回或标记无法判断 | `ReviewRequest` | `Review` / 200 | 首版 |
| POST | `/api/v1/reinspections` | 从已确认目标创建复检草稿任务 | `ReinspectionRequest` | `Task` / 201 | 首版 |

### 成果统计

| 方法 | 路径 | 用途 | 请求模型 | 返回数据 / 状态 | 范围 |
|---|---|---|---|---|---|
| GET | `/api/v1/statistics` | 查询任务和巡检汇总 | `—` | `Statistics` / 200 | 首版 |
| POST | `/api/v1/exports` | 异步导出航线或巡检结果 | `ExportRequest` | `JobAccepted` / 202 | 首版 |
| GET | `/api/v1/exports/{export_id}` | 读取已生成导出文件信息 | `—` | `Export` / 200 | 首版 |
| GET | `/api/v1/exports/{export_id}/content` | 下载导出成果文件 | `—` | `Export` / 200 | 首版 |

## 5. 关键请求和响应示例

### 5.1 创建巡检任务

`POST /api/v1/tasks`

```json
{
  "name": "青岚线 003—005 号杆塔精细巡检",
  "scene_id": "scn_demo",
  "line_id": "line_001",
  "target_ids": ["target_003_insulator", "target_004_insulator"],
  "takeoff_enu": {"x": 0, "y": -30, "z": 0},
  "landing_enu": {"x": 0, "y": -30, "z": 0},
  "constraints": {
    "speed_mps": 4,
    "max_task_duration_s": 900,
    "return_reserve_s": 120,
    "drone_radius_m": 0.6,
    "clearance_m": 3,
    "min_z_m": 0,
    "max_z_m": 80,
    "max_climb_rate_mps": 2
  }
}
```

服务端返回 201，data 为 Task，例如 task_id=`task_20261105_001`、status=`draft`、revision=1。服务端验证所有目标、线路、杆塔属于同一场景，并从当前数据生成 snapshot。上面均为仿真演示参数，不代表现场作业规范值。

### 5.2 生成拍摄点和航线

先 `POST /tasks/task_20261105_001/viewpoint-jobs`：

```json
{"task_revision":1,"scene_geometry_revision":1,"azimuth_samples":12,"height_samples":3}
```

拍摄点作业成功后调用 `GET /tasks/task_20261105_001/viewpoints?job_id=job_view_001&accepted_only=true`。如任一必需目标不存在可用拍摄点，规划返回可解释原因，不偷偷跳过目标。

再 `POST /tasks/task_20261105_001/planning-jobs`：

```json
{
  "task_revision":1,
  "scene_geometry_revision":1,
  "algorithm":"astar_3d",
  "visit_order":"nearest_neighbor_2opt",
  "grid_resolution_m":1,
  "simplify_path":true,
  "viewpoint_job_id":"job_view_001"
}
```

响应 HTTP 202；`Location: /api/v1/jobs/job_plan_001`：

```json
{"data":{"job_id":"job_plan_001","status":"queued","status_url":"/api/v1/jobs/job_plan_001"},"request_id":"req_plan_001"}
```

`GET /jobs/job_plan_001` 成功时 data.status=`succeeded`、result_type=`route`、result_id=`route_001`、result_url=`/api/v1/routes/route_001`。progress 是 0～1 的估计，不是飞行进度。规划成功不等于校验通过；需要下一步校验。

### 5.3 编辑、校验和回放

1. `GET /routes/route_001` 获得当前航点和 `ETag: "route_001:1"`。
2. `PATCH /routes/route_001`，带 If-Match，提交完整新 waypoints（以及可选 change_note）。服务端验证 waypoint_id 唯一、sequence 从 0 连续，起降点满足任务配置，capture 航点有相机参数和目标。返回新 revision=2，validation_status=`not_validated`。
3. `POST /routes/route_001/validation-jobs` 请求体：`{"route_revision":2,"scene_geometry_revision":1}`。
4. 轮询 Job；`GET /routes/route_001/validation?revision=2` 查看 ValidationResult。失败时 issues 包含问题类型、位置、航段或目标 ID。
5. 校验通过且依赖未变，路线成为活动航线，任务状态 ready；`GET /routes/route_001/simulation?revision=2&sample_interval_s=1` 返回位置采样、相机朝向和拍摄事件，前端完成时间轴回放。

响应中 coverage_ratio 取值 0～1，前端转百分数显示。min_clearance_m 为计算出的最近净间距；错误位置可点击三维定位。回放不证明实机飞行安全，真实飞控/动力学验证属于后续工作。

### 5.4 照片登记、识别和人工复核

先 multipart `POST /files`（purpose=image）获得 file_001，再 `POST /photos`：

```json
{
  "file_id":"file_001",
  "task_id":"task_20261105_001",
  "tower_id":"tower_003",
  "association_method":"manual_demo"
}
```

真实采集元数据可填写 capture_metadata、route_id、route_revision、waypoint_id、captured_at；服务端验证航点确实属于对应任务和版本。演示图库没有这些数据时明确标记 manual_demo，不伪造真实拍摄位置。

`POST /inference-jobs`：

```json
{"photo_ids":["photo_001"],"model_id":"model_insulator_v1","confidence_threshold":0.35}
```

提交后，通过 `GET /inference-jobs/job_ai_001/items` 查询每张输入照片的处理情况；结果中每个 photo_id 必须有一条记录。`status=succeeded, detection_count=0, error=null` 表示已完成但没有达到阈值的检测目标，`status=failed` 且 error 非空表示处理失败。不能把失败当成零检测。批次作业在所有图片处理结束后可 succeeded，逐图错误仍保留；若模型加载等批次级故障则 Job.failed，未执行图片需逐条记 failed 或 cancelled 并附原因。

通过 `GET /detections?job_id=job_ai_001` 获取有目标的识别结果。示例检测框为原图像素坐标：

```json
{
  "detection_id":"det_001",
  "photo_id":"photo_001",
  "tower_id":"tower_003",
  "job_id":"job_ai_001",
  "model_id":"model_insulator_v1",
  "model_version":"1.0.0",
  "class_name":"insulator",
  "confidence":0.91,
  "bbox_px":{"x_min":220,"y_min":160,"x_max":460,"y_max":390},
  "review_status":"unreviewed",
  "target_id":null,
  "latest_review":null
}
```

普通设备检测结果不能称为缺陷。仅使用相应缺陷模型和标注时，才输出疑似缺陷类别。模型置信度不是业务风险分数。

读取 detection 获取 ETag 后，`PUT /detections/det_001/review`：

```json
{"status":"confirmed","comment":"确认是目标绝缘子，需要侧面补拍","target_id":"target_003_insulator"}
```

再 `POST /reinspections`：

```json
{"source_task_id":"task_20261105_001","name":"003号杆塔复检","target_ids":["target_003_insulator"],"confirmed_detection_ids":["det_001"]}
```

返回新的 draft Task；起降点和约束默认复制源任务，snapshot 使用当前有效场景和目标版本，随后重新生成拍摄点、规划、校验。二维框不参与三维坐标推算；如果没有人工/元数据关联的 Target，应先人工选目标。

复核后重新 `GET /detections/det_001`（列表接口同样适用）读取 `latest_review`，其中包含 comment、target_id、reviewer_id 和 reviewed_at。无复核时为 null；review_status 与 latest_review.status 必须一致，刷新页面后仍可还原人工意见。

### 5.5 导出成果

`POST /exports`：`{"task_id":"task_20261105_001","kind":"route_json","route_id":"route_001","route_revision":2}`，返回导出 Job。route_json 条件下 JSON Schema 要求同时提交 route_id 和 route_revision，且服务端验证该航线属于该任务、该版本存在；不能只按版本号或最新活动航线推断。inspection_csv 不接受航线身份字段，提交时冻结本任务的照片、结果和复核快照。

成功后 result_id 为 export_001，读取 `GET /exports/export_001` 可获冻结身份：task_id、task_revision、scene_geometry_revision，以及 route_json 对应的 route_id、route_revision。通过 `GET /exports/export_001/content` 下载文件。route_json 包含坐标基准、路线版本和拍摄动作，仅为本系统交换格式。inspection_csv 汇总照片、检测结果、人工复核和来源；它不是一份诊断结论证明。导出固定快照，保留版本标记，不后台悄悄换成最新路线。

### 5.6 批量资产导入（扩展）

初版 UI 只提供单项维护，不提供批量导入按钮。后端预留扩展 `POST /import-jobs`，先将 JSON 数组文件以 purpose=import 上传，再提交 `{"file_id":"file_import_001","scene_id":"scn_demo","kind":"towers","validate_only":true}`。数组每行匹配对应的 LineCreate、TowerCreate 或 TargetCreate，服务端校验所有资源属于指定场景。

通过 `GET /import-jobs/job_import_001/items` 分页读取 row_index、status、resource_id、errors。预检通过行状态 valid，无效行 invalid 并给字段原因；运行中显示已校验行。确认后可用新的幂等键提交 validate_only=false，仍重新全量校验后原子提交；任意一行不合法则所有行不写入，有效行保持 valid、无效行 invalid，Job.failed；成功提交才是 created 并给 resource_id。该结果接口在 Job.failed 时仍可读，不将整批错误藏在一条通用消息里。

## 6. 状态与并发规则

### Task（巡检业务任务）

`draft → ready → completed`。未归档任务新建、修改参数或依赖过期回 draft；当前航线校验通过到 ready；用户确认归档且所有识别已复核到 completed。completed 不再直接修改，后续源场景变化不回 draft、不覆盖历史快照，只把 snapshot_status 标为 stale，可创建使用当前数据的新复检草稿。cancelled 为保留状态，本版不单独暴露取消业务任务接口；页面关闭草稿或取消计算不得混同“已取消任务”。

### Job（计算作业）

`queued → running → succeeded/failed`；queued 可直接 cancelled；running 收到取消请求先 cancel_requested，再 cancelled，或在取消检查前已完成则 succeeded。终态不可再次取消或改写。重试是重新 POST 创建新 Job。进程异常重启时，把遗留 running/cancel_requested 标记 failed（WORKER_INTERRUPTED），不无限显示运行。计算开始锁定参数快照，提交结果前检查依赖版本；不持有整个计算期间的数据库长事务。

### Route / Validation

新航线 not_validated → 校验 passed/failed；依赖变化 → stale。失败或过期路线可查看，不可使用仿真接口当作已通过路线。首版回放只开放通过且当前有效的版本，便于明确验收状态；历史版本仍可读取航点。修改路线时，通过 If-Match 防止多人覆盖；语义关系失效用 409。

### Detection / Review

unreviewed → confirmed/rejected/uncertain。uncertain 为已复核但无法判断；可再次人工修改，每次保留审计。模型重跑生成新的结果和 job_id，不覆写已有人工复核。task complete 要求无 unreviewed；uncertain 在报告里单独列出，不算确认缺陷。

## 7. 错误码与处理

| HTTP | 业务码示例 | 前端处理 |
|---|---|---|
| 400 | BAD_REQUEST | 提示请求格式问题 |
| 401 / 403 | UNAUTHENTICATED / FORBIDDEN | 登录或提示无权限 |
| 404 | RESOURCE_NOT_FOUND / VALIDATION_NOT_FOUND | 资源已删除或尚未计算 |
| 409 | STALE_SNAPSHOT / STALE_VALIDATION / VALIDATION_REQUIRED | 刷新依赖并重新规划或校验 |
| 409 | RESOURCE_IN_USE / INVALID_STATE / IDEMPOTENCY_CONFLICT | 解释当前业务冲突，勿静默覆盖 |
| 412 / 428 | ETAG_MISMATCH / PRECONDITION_REQUIRED | 重新读取资源再提交，保留用户本地草稿 |
| 413 / 415 | FILE_TOO_LARGE / UNSUPPORTED_MEDIA | 调整上传文件 |
| 422 | VALIDATION_ERROR / NO_VALID_VIEWPOINT / NO_FEASIBLE_ROUTE | 高亮字段或具体不可行目标 |
| 500 | INTERNAL_ERROR | 展示 request_id 便于定位，避免泄露内部栈 |

异步领域失败通过 Job.status=failed 与 Job.error 返回；HTTP 200 查询成功不代表业务计算成功。提交阶段已能检测的参数问题直接用 422。算法应给出“无可行解/预算耗尽”的具体原因，不把无法保证的路线包装为安全路线。

## 8. 页面与接口映射

| 前端页面 | 主要接口 | 关键交互 |
|---|---|---|
| 三维工作台 | scenes、lines、towers、targets、obstacles、routes | 场景加载、图层、点选和定位；名字修改与几何修改分开 |
| 线路资产/目标 | lines、towers、targets、files | 属性维护、部位标记、拍摄要求；模型文件先上传再引用 |
| 巡检任务 | tasks、viewpoint-jobs、planning-jobs、jobs | 新建配置、生成快照、显示阶段与失败原因 |
| 航线规划 | routes、versions、validation-jobs、validation | 编辑航点、If-Match保存、新版本失效提示、问题定位 |
| 仿真回放 | routes/{id}/simulation | 前端控制时间轴、暂停和倍速；不将播放按钮做成实机起飞 |
| AI识别复核 | files、photos、models、inference-jobs、detections、review | 上传、检测框、模型版本、人工确认、任务关联 |
| 复检 | reinspections + 标准规划链路 | 已确认目标进入新草稿，再次规划校验 |
| 成果统计 | statistics、exports、jobs、exports/{id}/content | 当前有效版本统计、异步导出 |
| 设置（扩展） | auth、users、models | 角色权限和受信任模型登记 |
| 资产批量导入（扩展） | files、import-jobs、import-jobs/{id}/items | JSON文件预检、行错误、全量原子提交；初版UI未提供按钮 |

## 9. 实施顺序与验收

第一步完成场景、线路杆塔、目标、文件和任务 CRUD；第二步实现拍摄点生成、规划作业与航线版本；第三步实现整段校验和回放；第四步接入离线训练的AI模型、复核和复检；最后补统计、导出与扩展鉴权。

验收至少包含：坐标一致性；起降与返航；细导线附近的航段穿越；编辑后校验失效；场景更新时异步结果不误激活；目标被遮挡/成像过小时不计覆盖；作业取消/崩溃/重复提交；图片元数据与任务不匹配；普通检测不误称缺陷；识别结果人工修正；历史版本导出可追溯。

OpenAPI文件可导入支持OpenAPI 3.1的接口工具查看。枚举、字段类型、请求/响应和分页结构以JSON契约为准；跨字段关系、版本失效、权限和算法约束需按本文实施。
