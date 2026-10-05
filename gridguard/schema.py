from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    asset: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: Literal["synthetic", "external-unvalidated"]
    protocol: Literal["iec61850-mms-report", "modbus_tcp", "iec104", "opcua", "mqtt"]
    timestamp_basis: Literal["source", "gateway-received"] = "source"
    quality_basis: Literal["iec61850-source", "gateway-normalized"] = "iec61850-source"
    temperature_c: float = Field(ge=-50, le=250)
    load_pu: float = Field(ge=0, le=2)
    vibration_g: float = Field(ge=0, le=20)
    sample_ms: int = Field(gt=0)
    channel_ms: tuple[int, int, int] = Field(strict=False)
    quality: tuple[int, int, int] = Field(strict=False)

    @model_validator(mode="after")
    def coherent(self) -> "Sample":
        if any(q < 0 or q > 8191 for q in self.quality):
            raise ValueError("quality is outside the 13-bit IEC 61850 field")
        if min(self.channel_ms) <= 0 or max(self.channel_ms) != self.sample_ms:
            raise ValueError("invalid channel timestamps")
        if max(self.channel_ms) - min(self.channel_ms) > 1000:
            raise ValueError("incoherent channel snapshot")
        return self
