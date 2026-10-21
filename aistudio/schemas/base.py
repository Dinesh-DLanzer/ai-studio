"""Shared configuration for runtime project document schemas."""
from pydantic import BaseModel, ConfigDict


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
