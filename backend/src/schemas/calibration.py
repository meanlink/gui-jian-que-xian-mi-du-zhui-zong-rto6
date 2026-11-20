from pydantic import BaseModel, Field


class CalibrationInput(BaseModel):
    default_offset_m: float = Field(default=0.0)
    run_offsets: dict = Field(default_factory=dict)
    note: str = Field(default='', max_length=300)
