from pydantic import BaseModel, ConfigDict


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cliente_id: str = "default"
    include_macro: bool = True
    train_model: bool = True
