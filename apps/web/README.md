# 创建 Vue3 + TypeScript 前端
```
pnpm create vite@latest apps/web --template vue-ts --no-interactive

pnpm --dir apps/web add vue-router pinia element-plus @element-plus/icons-vue axios cesium echarts
pnpm --dir apps/web add -D vite-plugin-static-copy
pnpm add -Dw concurrently openapi-typescript

New-Item -ItemType File -Force apps/api/app/__init__.py | Out-Null
```