# 创建后端启动入口和健康检查
from uuid import uuid4
from fastapi import FastAPI, Response

app = FastAPI(
    title="电巡智航 API",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

@app.get("/api/v1/health")
def health(response: Response) -> dict:
    """检查后端服务状态，用于验证前后端通信。"""
    request_id = uuid4().hex
    response.headers["X-Request-ID"] = request_id
    return {"data": {"status": "ok"}, "request_id": request_id}
