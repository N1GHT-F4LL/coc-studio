"""REST: list migrated deploy scenarios (data/scenarios/).

Used to populate the 'scenario' dropdown on the deploy block. Scenarios are
created by the migrator (scripts/migrate_scenario.py).
"""
import logging

from fastapi import APIRouter

import scenario_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios():
    return {"scenarios": scenario_store.list_scenarios()}
