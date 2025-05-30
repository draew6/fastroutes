from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass


def get_model_name(return_type: BaseModel | ModelMetaclass):
    return (
        "".join(word.capitalize() for word in return_type.__module__.split("."))
        + return_type.__name__
    )
