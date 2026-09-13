from pydantic import BaseModel


class AgentModel(BaseModel):
    def to_dict(self) -> dict:
        return self.model_dump()
