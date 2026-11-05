
## 目录含义
power-inspection/
├─ apps/                # 放前端和后端项目
│  └─ web/              # 前端项目
├─ packages/
│  └─ contracts/        # 放接口契约文件
└─ docs/
   └─ ui/               # 放 UI 原型和设计资料

## 安装工具
npm install -g pnpm
python -m pip install --user uv

## 创建 monorepo
mkdir power-inspection
cd power-inspection
git init

New-Item -ItemType Directory -Force apps, packages/contracts, docs/ui | Out-Null

## 根据接口契约生成前端 TypeScript 类型
`pnpm generate:api`

## 启动前后端骨架
### 前端：http://127.0.0.1:5173
### 后端文档：http://127.0.0.1:8000/api/v1/docs
`pnpm dev`

## 后续安装 AI 依赖时，在项目根目录执行
python -m uv --directory apps/api add ultralytics opencv-python