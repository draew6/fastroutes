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

---

## 📦 Installation

```bash
pip install git+https://github.com/draew6/fastroutes
```

## 🛠️ Usage
### 1. Add FastRoutes to your FastAPI app:
```python
from fastapi import FastAPI
from fastroutes import FastRoutes

app = FastAPI()
FastRoutes(app, name="MyVeryNiceClient").add_route_to_fastapi()
```
This will add a /fastroutes endpoint that servers your generated client code.
### 2. Download the generated client code:
```bash
fastroutes http://localhost:8000/fastroutes output_file.py
```
This will save the generated ccode to `output_file.py`.
