"""
DataFrame CRUD Storage Layer.

Voice-driven CRUD operations over per-user pandas DataFrames backed by
parquet files. Phase 1 of a 3-layer architecture:
    Layer 1: Storage + schemas + CRUD operations (this package)
    Layer 2: Phi-4 14B intent extraction + Claude Code headless fallback
    Layer 3: Dispatcher with semantic caching + voice I/O
"""

__version__ = "0.1.0"

from cosa.crud_for_dataframes.schemas import (
    get_schema,
    get_columns,
    get_defaults,
    get_date_columns,
    get_time_columns,
    get_datetime_columns,
    validate_schema_type,
    VALID_SCHEMA_TYPES,
    SCHEMAS,
)

from cosa.crud_for_dataframes.xml_models import CRUDIntent

from cosa.crud_for_dataframes.storage import DataFrameStorage

from cosa.crud_for_dataframes.crud_operations import (
    create_list,
    delete_list,
    list_lists,
    add_item,
    delete_item,
    update_item,
    mark_done,
    query_items,
    get_schema_info,
)

# Phase 2: Intent dispatch and voice formatting
from cosa.crud_for_dataframes.dispatcher import dispatch, format_result_for_voice
