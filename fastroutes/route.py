from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic_core import PydanticUndefined
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
import textwrap
from dataclasses import dataclass
from typing import Any, Literal, get_origin, get_args, Union
from types import NoneType
from .helpers import get_model_name
from datetime import datetime


PARAMETER_UNDEFINED = "_PARAMETER_UNDEFINED"
METHOD = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]


@dataclass(frozen=True)
class Parameter:
    alias: str
    type: type[Any]
    required: bool
    default: Any = PARAMETER_UNDEFINED

    def __hash__(self):
        return hash((self.alias, self.type, self.required))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Parameter):
            return NotImplemented
        return (self.alias, self.type, self.required, self.default) == (
            other.alias,
            other.type,
            other.required,
            other.default,
        )

    def __str__(self):
        type_ = self.type
        origin = get_origin(type_)
        args = get_args(type_)

        if origin is None:
            type_repr = type_.__name__
        elif origin is Union:
            type_repr = " | ".join(t.__name__ for t in args).replace("NoneType", "None")
        elif origin is list:
            if len(args) == 1:
                if isinstance(args[0], ModelMetaclass):
                    model_name = get_model_name(args[0])
                    type_repr = f"list[{model_name}]"
                else:
                    type_repr = str(type_).replace("datetime.datetime", "datetime")
            else:
                raise ValueError("List type must have exactly one argument.")
        else:
            type_repr = str(type_).replace("datetime.datetime", "datetime")
        if self.default != PARAMETER_UNDEFINED:
            return f"{self.alias}: {type_repr} = {self.default!r}"
        return f"{self.alias}: {type_repr}"


@dataclass
class Route:
    index: int
    name: str
    method: METHOD
    path: str
    description: str
    body: BaseModel | None
    path_parameters: list[Parameter]
    query_parameters: list[Parameter]
    response: Any

    @property
    def return_types(self):
        return (
            [self.body] + self.path_parameters + self.query_parameters + [self.response]
        )

    @property
    def body_parameters(self):
        if not self.body:
            return []
        return [
            Parameter(
                name,
                info.annotation,
                info.is_required(),
                info.default
                if info.default is not PydanticUndefined
                else PARAMETER_UNDEFINED,
            )
            for name, info in self.body.model_fields.items()
        ]

    @property
    def response_signature(self):
        if get_origin(self.response) is list:
            return_type = get_args(self.response)[0]

            if isinstance(return_type, ModelMetaclass):
                model_name = get_model_name(return_type)
                return f"list[{model_name}]"
            elif get_origin(return_type) is Literal:
                return f"list[Literal[{', '.join(f"'{str(arg)}'" for arg in get_args(return_type))}]]"
            return f"list[{return_type.__name__}]"

        elif get_origin(self.response) is dict:
            rt = get_args(self.response)
            return_type = rt[1]
            if isinstance(return_type, ModelMetaclass):
                model_name = get_model_name(return_type)
                return f"dict[{rt[0].__name__}, {model_name}]"
            return f"dict[{rt[0].__name__}, {rt[1].__name__}]"
        elif self.response is None:
            return "None"
        else:
            if isinstance(self.response, ModelMetaclass):
                model_name = get_model_name(self.response)
                return model_name
            return_type = self.response
            return f"{return_type.__name__}"

    @property
    def handler(self):
        params = ", ".join(
            str(param)
            for param in sorted(
                self.body_parameters + self.path_parameters + self.query_parameters,
                key=lambda p: not p.required,
            )
        )
        signature = (
            f"""async def {self.name}(self, {params}) -> {self.response_signature}:\n"""
        )
        docstring = textwrap.indent(f'"""{self.description}"""', "    ")

        url_body = textwrap.indent(
            f"url = {'f' if self.path_parameters else ''}'{self.path}'", "    "
        )
        params_dict = ", ".join(
            f'"{query_param.alias}":{query_param.alias}'
            for query_param in self.query_parameters
        )
        if self.query_parameters:
            params_body = textwrap.indent(f"params = {{{params_dict}}}", "    ")
        else:
            params_body = textwrap.indent("params = None", "    ")
        payload_dict = ", ".join(
            f'"{body_param.alias}":{body_param.alias}{".isoformat()" if body_param.type is datetime else ""}'
            for body_param in self.body_parameters
        )
        if self.body_parameters:
            payload_body = textwrap.indent(f"payload = {{{payload_dict}}}", "    ")
        else:
            payload_body = textwrap.indent("payload = None", "    ")
        httpx_body = textwrap.indent(
            f'api_response = await self._client.request("{self.method}", url, json=payload, params=params)',
            "    ",
        )
        raise_error_body = textwrap.indent("api_response.raise_for_status()", "    ")

        is_list = self.response_signature.startswith("list[")
        is_dict = self.response_signature.startswith("dict[")
        if is_list:
            response_model = self.response_signature[5:-1]
        elif is_dict:
            response_model = self.response_signature[5:-1].split(", ")[1]
        else:
            response_model = self.response_signature
        if self.response is not None:
            response_json_body = textwrap.indent(
                "response_body = api_response.json()", "    "
            )
        else:
            response_json_body = textwrap.indent(
                "", "    "
            )

        asterisk = "**" if self.response_signature != "list[int]" and not self.response_signature.endswith(", list]") else ""
        if is_dict and self.response_signature.endswith("int]"):
            asterisk = ""
        if self.response is None:
            parse_body = textwrap.indent("return None", "    ")
        elif is_list:
            if "Literal" in self.response_signature:
                parse_body = textwrap.indent(
                    f"return [resp_object for resp_object in response_body]\n",
                    "    ",
                )
            else:
                parse_body = textwrap.indent(
                    f"return [{response_model}({asterisk}resp_object) for resp_object in response_body]\n",
                    "    ",
                )
        elif is_dict:
            parse_body = textwrap.indent(
                f"return {{key: {response_model}({asterisk}value) for key, value in response_body.items()}}",
                "    ",
            )
        else:
            parse_body = textwrap.indent(
                f"return {response_model}({asterisk}response_body)", "    "
            )

        return (
            signature
            + docstring
            + "\n"
            + url_body
            + "\n"
            + params_body
            + "\n"
            + payload_body
            + "\n"
            + httpx_body
            + "\n"
            + raise_error_body
            + "\n"
            + response_json_body
            + "\n"
            + parse_body
        )

    @staticmethod
    def get_method(methods: set) -> METHOD:
        method_priority: list[METHOD] = [
            "GET",
            "POST",
            "DELETE",
            "PUT",
            "PATCH",
            "HEAD",
            "OPTIONS",
        ]
        for method in method_priority:
            if method in methods:
                return method
        raise ValueError(
            f"Method not found in {methods}. Expected one of {method_priority}."
        )

    @classmethod
    def extract(cls, app: FastAPI, paths_to_exclude: list[str] = None) -> list["Route"]:
        routes = []
        for index, route in enumerate(app.routes):
            if not isinstance(route, APIRoute):
                continue
            if paths_to_exclude and route.path in paths_to_exclude:
                continue
            name = route.name
            description = route.description

            path = route.path
            method = cls.get_method(route.methods)
            path_parameters = [
                Parameter(
                    param.alias,
                    param.type_,
                    param.required,
                    param.default
                    if param.default is not PydanticUndefined
                    else PARAMETER_UNDEFINED,
                )
                for param in route.dependant.path_params
            ]
            query_parameters = [
                Parameter(
                    param.alias,
                    param.type_,
                    param.required,
                    param.default
                    if param.default is not PydanticUndefined
                    else PARAMETER_UNDEFINED,
                )
                for param in route.dependant.query_params
            ]

            body = route.body_field.type_ if route.body_field else None

            response = route.response_model
            routes.append(
                cls(
                    index,
                    name,
                    method,
                    path,
                    description,
                    body,
                    path_parameters,
                    query_parameters,
                    response,
                )
            )
        return routes
