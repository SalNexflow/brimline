"""The fictional shop's configuration (config/shop.toml), validated before anything uses it."""

import datetime as dt
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brimline_engine.permissions import Role
from brimline_engine.settings import REPO_ROOT

SHOP_CONFIG_PATH = REPO_ROOT / "config" / "shop.toml"

Process = Literal["fdm", "resin", "cnc"]
PostProcess = Literal["sanding", "painting", "assembly"]


class _Strict(BaseModel):
    # Unknown keys are typos, not features.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Shop(_Strict):
    name: str
    time_zone: str
    currency: str


class Customer(_Strict):
    code: str
    name: str
    email: str


class User(_Strict):
    code: str
    display_name: str
    role: Role
    customer: str | None = None


class Material(_Strict):
    code: str
    name: str
    process: Process
    color: str


class Machine(_Strict):
    code: str
    name: str
    process: Process
    build_mm: tuple[int, int, int]
    materials: list[str]


class Shift(_Strict):
    weekdays: list[int] = Field(min_length=1)
    starts: dt.time
    ends: dt.time


class PriceRules(_Strict):
    effective_from: dt.date
    setup_cents: int = Field(ge=0)
    machine_minute_cents: dict[Process, int]
    material_cents_per_gram: dict[str, int]
    rush_multiplier_percent: int = Field(ge=100, le=500)
    post_process_cents_per_part: dict[PostProcess, int]


class OrderLine(_Strict):
    part: str
    quantity: int = Field(gt=0)
    material: str
    # What the scheduler needs; optional, so a line can be seeded as "cannot plan yet".
    minutes_per_part: int | None = Field(default=None, gt=0)
    part_mm: tuple[int, int, int] | None = None
    post: list[PostProcess] = []


class Order(_Strict):
    customer: str
    created_by: str
    due_date: dt.date
    rush: bool = False
    notes: str = ""
    lines: list[OrderLine] = Field(min_length=1)


class ShopConfig(_Strict):
    checked: dt.date
    seed_time: dt.datetime
    shop: Shop
    customers: list[Customer]
    users: list[User]
    materials: list[Material]
    machines: list[Machine]
    stock: dict[str, int]
    shifts: list[Shift]
    price_rules: PriceRules
    orders: list[Order] = []

    @model_validator(mode="after")
    def references_exist(self) -> "ShopConfig":
        """Every code mentioned anywhere must be defined, so a typo fails here, not in SQL."""
        customers = {c.code for c in self.customers}
        users = {u.code for u in self.users}
        materials = {m.code: m.process for m in self.materials}
        problems: list[str] = []

        for u in self.users:
            if (u.role == "customer") != (u.customer is not None):
                problems.append(f"user {u.code}: only customer users have a customer")
            if u.customer is not None and u.customer not in customers:
                problems.append(f"user {u.code}: unknown customer {u.customer}")
        for m in self.machines:
            for code in m.materials:
                if materials.get(code) != m.process:
                    problems.append(
                        f"machine {m.code}: {code} is unknown or not a {m.process} material"
                    )
        for code in [*self.stock, *self.price_rules.material_cents_per_gram]:
            if code not in materials:
                problems.append(f"unknown material {code}")
        unpriced = set(materials) - set(self.price_rules.material_cents_per_gram)
        if unpriced:
            problems.append(f"materials without a price: {sorted(unpriced)}")
        for i, o in enumerate(self.orders, start=1):
            if o.customer not in customers:
                problems.append(f"order {i}: unknown customer {o.customer}")
            if o.created_by not in users:
                problems.append(f"order {i}: unknown user {o.created_by}")
            problems += [
                f"order {i}: unknown material {line.material}"
                for line in o.lines
                if line.material not in materials
            ]
        if problems:
            raise ValueError("; ".join(problems))
        return self


def load_shop_config(path: Path = SHOP_CONFIG_PATH) -> ShopConfig:
    with path.open("rb") as f:
        return ShopConfig.model_validate(tomllib.load(f))
