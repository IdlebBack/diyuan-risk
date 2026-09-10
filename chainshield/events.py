"""风险事件库查询工具。"""

from __future__ import annotations

import pandas as pd

from .repository import Repository
from .risk import confirmed_event_mask


def active_events(repo: Repository) -> pd.DataFrame:
    return repo.events[confirmed_event_mask(repo.events)].reset_index(drop=True)


def pending_verification(repo: Repository) -> pd.DataFrame:
    if repo.events.empty:
        return repo.events.copy()
    status = repo.events["status"].astype(str).str.lower()
    return repo.events[(status.isin(["active", "verify"])) & ~confirmed_event_mask(repo.events)].reset_index(drop=True)


def event_status_counts(repo: Repository) -> pd.DataFrame:
    return (
        repo.events.groupby("status")
        .size()
        .rename("数量")
        .to_frame()
        .reset_index()
    )
