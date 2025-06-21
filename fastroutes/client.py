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
            "from models import *\n"
            "from pydantic import BaseModel, StringConstraints, Field, EmailStr\n"
            "from typing import Annotated, Literal, Optional\n"
            "import httpx\n"
            "import typing\n"
            "from datetime import datetime\n\n\n"
        )

    def get_models(self) -> str:
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
                    list_element = list(get_args(return_type))[0]
                    if isinstance(list_element, ModelMetaclass):
                        models.append(list_element)
                        models = get_models_from_fields(list_element, models)

            if models:
                print("those are here", models)
            return models

        already_written = [get_model_name(BaseModel)]

        mapping = {}
        relationships = defaultdict(list[Model])
        all_models: list[tuple[str, Model, BaseModel]] = []

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
                        for rtm in get_models_from_fields(rt) + [rt]:
                            model_name = get_model_name(rtm)
                            if model_name in already_written:
                                continue
                            mapping[rtm.__name__] = model_name
                            mdl = Model(
                                model_name,
                                self.strip_decorators_from_source(rtm).replace(
                                    f"class {rtm.__name__}", f"class {model_name}"
                                ),
                                get_model_name(rtm.__base__),
                            )
                            relationships[get_model_name(rtm.__base__)] += [mdl]

                            already_written.append(model_name)
                            all_models.append((get_model_name(rtm), mdl, rtm))

        correct_order = []
        correct_order_names = []

        def dfs(parent_name: str) -> None:
            """
            Depth-first preorder walk:
            append every direct child of *parent_name*,
            then recurse into that child's own descendants.
            """
            for child in relationships.get(parent_name, []):
                correct_order.append(child)  # parent is already earlier
                correct_order_names.append(child.name)
                dfs(child.name)

        def extract_parents(model: BaseModel, models_to_export: list[BaseModel] = None):
            if models_to_export is None:
                models_to_export = []
            parent = model.__base__
            if parent is BaseModel:
                return models_to_export
            return extract_parents(parent, [parent] + models_to_export)

        dfs("PydanticMainBaseModel")

        for model_name, model, pydantic_model in all_models:
            if model_name not in correct_order_names:
                to_add = extract_parents(pydantic_model)
                correct_order = [
                    Model(
                        model_name,
                        self.strip_decorators_from_source(to_a).replace(
                            f"class {to_a.__name__}", f"class {model_name}"
                        ),
                        get_model_name(to_a),
                    )
                    for to_a in to_add
                ] + correct_order

        models_code = ""
        for model in correct_order:
            models_code += model.code + "\n\n"

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
