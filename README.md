# fast-routes

**Generate typed HTTP clients from FastAPI apps automatically.**  
This library inspects your FastAPI app and produces a fully usable async client with request/response models — ideal for service-to-service communication or rapid prototyping.

---

## 🚀 Features

- Extracts all FastAPI routes.
- Generates:
  - Request/response models
  - Method handlers (with typed parameters)
  - A reusable HTTP client class
- Provides a download endpoint (`/fastroutes`) and a CLI tool to fetch generated code.

