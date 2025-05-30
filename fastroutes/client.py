import textwrap
from io import BytesIO
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic._internal._model_construction import ModelMetaclass
import inspect
from typing import get_origin, get_args
from .route import Route
from .helpers import get_model_name


class FastRoutes:
    def __init__(self, app: FastAPI, name: str, paths_to_exclude: list[str] = None):
        self.app = app
        self.routes = Route.extract(app, paths_to_exclude=paths_to_exclude)
        self.name = name

    @staticmethod
    def get_imports():
        return (
            "from pydantic import BaseModel, StringConstraints, Field, EmailStr\n"
            "from typing import Annotated\n"
            "import httpx\n\n\n"
        )

    def get_models(self) -> str:
        already_written = []
        mapping = {}
        models_code = ""
        for route in self.routes:
            for return_type in route.return_types:
                if get_origin(return_type) is list:
                    rts = list(get_args(return_type))
                else:
                    rts = [return_type]
                for rt in rts:
                    if isinstance(rt, ModelMetaclass):
                        model_name = get_model_name(rt)
                        if model_name in already_written:
                            continue
                        mapping[rt.__name__] = model_name
                        models_code += self.strip_decorators_from_source(rt).replace(
                            f"class {rt.__name__}", f"class {model_name}"
                        )
                        models_code += "\n\n"
                        already_written.append(model_name)
        for old_value, new_value in mapping.items():
            models_code = models_code.replace(
                f"({old_value})", f"({new_value})"
            ).replace(f": {old_value}", f": {new_value}")
        return models_code + "\n\n\n"

    @staticmethod
    def strip_decorators_from_source(cls: type) -> str:
        src = inspect.getsource(cls)
        lines = []
        for line in src.splitlines():
            if line.lstrip().startswith("@") or line.lstrip().startswith("def "):
                break
            lines.append(line)
        return "\n".join(lines)

    def get_handlers(self) -> str:
        handlers_code = ""
        for route in self.routes:
            handlers_code += route.handler + "\n\n"
        return handlers_code

    def get_client_class(self) -> str:
        class_code = (
            f"class {self.name}:\n"
            "    def __init__(self):\n"
            "       self._client = httpx.AsyncClient()\n\n"
            "    async def __aenter__(self):\n"
            "       return self\n\n"
            "    async def __aexit__(self, exc_type, exc, tb):\n"
            "       await self._client.aclose()\n\n\n"
        )
        return class_code

    def export_code(self) -> str:
        imports = self.get_imports()
        models = self.get_models()
        client_class = self.get_client_class()
        handlers = self.get_handlers()
        return imports + models + client_class + textwrap.indent(handlers, "    ")

    def add_route_to_fastapi(self):
        @self.app.get("/fastroutes", include_in_schema=False)
        async def get_fastroutes():
            content = self.export_code()
            file_like = BytesIO(content.encode("utf-8"))
            headers = {
                "Content-Disposition": f"attachment; filename={self.name.lower()}.py",
            }
            return StreamingResponse(
                file_like, media_type="text/x-python", headers=headers
            )
