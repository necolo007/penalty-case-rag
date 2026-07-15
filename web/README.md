# 案库 Web 前端

Vite + React 19 + TypeScript + Tailwind CSS 4，对接 `penalty-case-rag` FastAPI（`/api/v1/*`）。

## 开发

需先启动后端（默认 `http://127.0.0.1:8000`）：

```bash
cd web
npm install
npm run dev
```

开发服务器：`http://localhost:5173`（`/api` 已代理到后端）。

## 生产构建（由 FastAPI 托管）

```bash
cd web
npm run build
```

产物在 `web/dist/`。重启 / 刷新 API 后访问 `http://localhost:8000/`。

## 页面

| 路由 | 功能 | 接口 |
|------|------|------|
| `/` | 知识库总览 | `GET /api/v1/stats` |
| `/search` | 相似案例检索 | `POST /api/v1/search/retrieve` |
| `/cases` | 案例库浏览 | `GET /api/v1/cases` |
| `/cases/:id` | 案例详情 | `GET /api/v1/cases/{id}` |
| `/documents` | 文档上传与状态 | `POST/GET /api/v1/documents*` |
| `/review` | 合规审查 | `POST /api/v1/review/*` |
