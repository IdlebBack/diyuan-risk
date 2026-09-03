"""风险事件库查询工具。"""

from __future__ import annotations

import pandas as pd

from .repository import Repository


def active_events(repo: Repository) -> pd.DataFrame:
    return repo.events[repo.events["status"] == "active"].reset_index(drop=True)


def pending_verification(repo: Repository) -> pd.DataFrame:
    return repo.events[repo.events["status"] == "verify"].reset_index(drop=True)


def event_status_counts(repo: Repository) -> pd.DataFrame:
    return (
        repo.events.groupby("status")
        .size()
        .rename("数量")
        .to_frame()
        .reset_index()
    )
