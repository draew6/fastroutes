import textwrap
from collections import defaultdict
from io import BytesIO
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
import inspect
from typing import get_origin, get_args
from .route import Route
from .helpers import get_model_name
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str
    code: str
    parent_name: str | None = None


class FastRoutes:
    def __init__(self, app: FastAPI, name: str, paths_to_exclude: list[str] = None):
        self.app = app
        self.routes = Route.extract(app, paths_to_exclude=paths_to_exclude)
        self.name = name

    @staticmethod
    def get_imports():
        return (
            "# flake8: noqa: F401, F403, F405\n"
            "from models import *\n"
            "from pydantic import BaseModel, StringConstraints, Field, EmailStr\n"
            "from typing import Annotated, Literal, Optional\n"
            "import httpx\n"
            "import typing\n"
            "from datetime import datetime\n\n\n"
        )

    def get_models(self) -> str:
        def extract_parents(model: BaseModel, models_to_export: list[BaseModel] = None):
            if models_to_export is None:
                models_to_export = []
            parent = model.__base__
            if parent is BaseModel:
                return models_to_export
            return extract_parents(parent, [parent] + models_to_export)

        def get_models_from_fields(model: BaseModel, models=None) -> list[BaseModel]:
            """
            Recursively extract all models from the fields of a given model.
            """
            if models is None:
                models = []
            for field in model.model_fields.values():
                if isinstance(field.annotation, ModelMetaclass):
                    models.append(field.annotation)
                    models = get_models_from_fields(field.annotation, models)
                elif get_origin(field.annotation) is list:
                    list_element = list(get_args(field.annotation))[0]
                    if isinstance(list_element, ModelMetaclass):
                        models.append(list_element)
                        models = get_models_from_fields(list_element, models)

            return models

        all_models = {}
        relationships = defaultdict(list[str])
        mapping = {}
        base_models = {}
        for route in self.routes:
            for return_type in route.return_types:
                if get_origin(return_type) is list:
                    rts = list(get_args(return_type))
                elif get_origin(return_type) is dict:
                    rts = list(get_args(return_type))
                else:
                    rts = [return_type]
                for rt in rts:
                    if isinstance(rt, ModelMetaclass):
                        models_in_model = get_models_from_fields(rt)
                        models_in_model = models_in_model + [item for list in [extract_parents(mim) for mim in models_in_model + [rt]] for item in list] + [rt]
                        for relevant_model in models_in_model:
                            model_name = get_model_name(relevant_model)
                            all_models[model_name] = Model(
                                model_name,
                                self.strip_decorators_from_source(relevant_model).replace(
                                    f"class {relevant_model.__name__}", f"class {model_name}"
                                ),
                                get_model_name(relevant_model.__base__),
                            )
                            base_models[model_name] = relevant_model
                            mapping[relevant_model.__name__] = model_name
        for model_name, model in base_models.items():
            parent_model_name = get_model_name(model.__base__)
            models_in_model = get_models_from_fields(model)
            relationships[model_name] = [get_model_name(m) for m in models_in_model] + [parent_model_name]

        correct_order = []

        def add_to_order(model_name: str) -> None:
            """
            Add a model to the order list, ensuring no duplicates.
            """
            if model_name not in correct_order:
                correct_order.append(model_name)
            for model, dependencies in relationships.items():
                new_dependencies = [ dep for dep in dependencies if dep != model_name ]
                relationships[model] = new_dependencies

        add_to_order("PydanticMainBaseModel")
        while True:
            ready = [model for model, deps in relationships.items() if not deps and model not in correct_order]
            if not ready:
                break
            for model in ready:
                add_to_order(model)

        models_code = ""
        for model_name in correct_order[1:]:
            model = all_models[model_name]
            models_code += model.code + "\n\n"

        for old_value, new_value in mapping.items():
            models_code = models_code.replace(
                f"({old_value})", f"({new_value})"
            ).replace(f": {old_value}", f": {new_value}").replace(f"[{old_value}]", f"[{new_value}]")
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
            "    def __init__(self, base_url: str):\n"
            "       self._client = httpx.AsyncClient(base_url=base_url)\n\n"
            "    async def __aenter__(self):\n"
            "       return self\n\n"
            "    async def __aexit__(self, exc_type, exc, tb):\n"
            "       await self._client.aclose()\n\n\n"
            "    def set_access_token(self, access_token: str | None):\n"
            "        if access_token:\n"
            '            self._client.headers.update({"Authorization": f"Bearer {access_token}"})\n'
            "        else:\n"
            '            self._client.headers.pop("Authorization", None)\n\n\n'
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
