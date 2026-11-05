# 创建 FastAPI 后端
```
python -m uv init apps/api --bare --python 3.12
python -m uv --directory apps/api python pin 3.12

python -m uv --directory apps/api add "fastapi[standard]" sqlalchemy alembic pydantic-settings python-multipart numpy scipy
python -m uv --directory apps/api add --dev pytest httpx ruff

New-Item -ItemType Directory -Force apps/api/app, apps/api/tests, apps/api/var | Out-Null
New-Item -ItemType File -Force apps/api/app/__init__.py | Out-Null
```