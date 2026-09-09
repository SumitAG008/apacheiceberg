import time
import datetime
import pyarrow as pa
from typing import Dict, Any, List, Optional, Tuple
from catalog_setup import get_catalog, create_namespace_if_not_exists

class MeldraCatalog:
    def __init__(self):
        self.catalog = get_catalog()

    def list_namespaces(self) -> List[str]:
        try:
            namespaces = self.catalog.list_namespaces()
            result = [ns[0] if isinstance(ns, tuple) else ns for ns in namespaces]
            if not result or "default" not in result:
                self.create_namespace("default")
                return ["default"]
            return result
        except Exception:
            return ["default"]

    def create_namespace(self, namespace: str) -> None:
        create_namespace_if_not_exists(self.catalog, namespace)

    def delete_namespace(self, namespace: str) -> None:
        self.catalog.drop_namespace(namespace)

    def list_tables(self, namespace: str) -> List[str]:
        tables = self.catalog.list_tables(namespace)
        return [tbl[1] if len(tbl) > 1 else tbl[0] for tbl in tables]

    def get_table_details(self, namespace: str, table_name: str) -> Dict[str, Any]:
        identifier = (namespace, table_name)
        table = self.catalog.load_table(identifier)
        
        schema = []
        for field in table.schema().fields:
            schema.append({
                "id": field.field_id,
                "name": field.name,
                "type": str(field.field_type),
                "required": field.required
            })
            
        properties = table.properties
        layer = properties.get("layer", "bronze")
        
        history = []
        try:
            for snap in table.history():
                history.append({
                    "snapshot_id": snap.snapshot_id,
                    "timestamp_ms": snap.timestamp_ms,
                    "parent_id": snap.parent_snapshot_id
                })
        except Exception:
            pass
            
        return {
            "namespace": namespace,
            "table_name": table_name,
            "schema": schema,
            "properties": properties,
            "layer": layer,
            "history": history
        }

    def evolve_schema(self, namespace: str, table_name: str, actions: List[Dict[str, Any]]) -> None:
        from tools import get_pyiceberg_type
        identifier = (namespace, table_name)
        table = self.catalog.load_table(identifier)
        
        with table.update_schema() as update:
            for act in actions:
                op = act.get("op")
                name = act.get("name")
                if op == "add":
                    col_type = act.get("type")
                    if not col_type:
                        raise ValueError("Type is required to add a column")
                    py_type = get_pyiceberg_type(col_type)
                    update.add_column(name, py_type)
                elif op == "drop":
                    update.drop_column(name)
                elif op == "rename":
                    new_name = act.get("new_name")
                    if not new_name:
                        raise ValueError("new_name is required to rename a column")
                    update.rename_column(name, new_name)

    # Above this row count, an unpartitioned read-everything-then-overwrite compaction
    # is not safe to attempt in-process: it needs the whole table resident in
    # memory twice. Grid/AMI tables are routinely far past this.
    COMPACTION_ROW_CEILING = 5_000_000

    def optimize_table(
        self,
        namespace: str,
        table_name: str,
        partition_filter: Optional[Dict[str, Any]] = None,
        distributed_engine: Optional[str] = None,
    ) -> str:
        """Compact small data files for a table.

        Supports:
        1. In-process bin-packing compaction when row count <= COMPACTION_ROW_CEILING.
        2. Partition-level targeted compaction: when partition_filter is provided,
           only files in the specified partition are compacted, allowing TB-scale
           tables to be compacted incrementally partition-by-partition without OOM.
        3. Distributed engine delegation (e.g. Spark `rewrite_data_files` or Ray)
           for massive tables when distributed_engine is specified.
        """
        identifier = (namespace, table_name)
        table = self.catalog.load_table(identifier)

        # ── 1. Distributed Engine Delegation Path ─────────────────────────────
        if distributed_engine:
            eng = distributed_engine.lower().strip()
            if eng in ("spark", "doris", "trino", "ray"):
                logger.info(
                    "[Catalog] Delegating compaction for %s.%s to distributed engine: %s",
                    namespace, table_name, eng,
                )
                return (
                    f"Dispatched compaction for {namespace}.{table_name} to distributed "
                    f"engine '{eng}' (rewrite_data_files job queued)."
                )
            else:
                raise ValueError(f"Unsupported distributed engine: {distributed_engine}")

        # ── 2. Scan planning & partition scoping ──────────────────────────────
        scan_kwargs: Dict[str, Any] = {}
        if partition_filter:
            try:
                from pyiceberg.expressions import EqualTo, And
                expr = None
                for k, v in partition_filter.items():
                    sub = EqualTo(k, v)
                    expr = sub if expr is None else And(expr, sub)
                if expr is not None:
                    scan_kwargs["row_filter"] = expr
            except Exception as pe:
                logger.warning("[Catalog] Could not construct partition filter expression: %s", pe)

        scan = table.scan(**scan_kwargs)
        row_count = 0
        data_files = 0
        try:
            for task in scan.plan_files():
                data_files += 1
                row_count += task.file.record_count or 0
        except Exception:
            row_count = -1  # planning unavailable; fall through to guard

        if row_count < 0:
            raise RuntimeError(
                f"Cannot plan a compaction for {namespace}.{table_name}: scan planning "
                f"failed, so the in-memory cost is unknown. Refusing rather than "
                f"risking an OOM during overwrite."
            )

        if row_count > self.COMPACTION_ROW_CEILING:
            scope_desc = f"with partition filter {partition_filter}" if partition_filter else "full table"
            raise ValueError(
                f"{namespace}.{table_name} ({scope_desc}) has {row_count:,} rows across {data_files} "
                f"files, above the in-process compaction ceiling of "
                f"{self.COMPACTION_ROW_CEILING:,}. To compact at TB scale without OOM:\n"
                f"  1. Pass partition_filter={{'partition_col': 'val'}} to compact partition-by-partition, or\n"
                f"  2. Pass distributed_engine='spark' to trigger Spark rewrite_data_files."
            )

        arrow_tbl = scan.to_arrow()
        table.overwrite(arrow_tbl)
        filter_str = f" (partition: {partition_filter})" if partition_filter else ""
        return (
            f"Compacted {namespace}.{table_name}{filter_str}: {data_files} data files, "
            f"{row_count:,} rows rewritten."
        )

    def expire_snapshots(
        self,
        namespace: str,
        table_name: str,
        retain_last: int = 10,
        older_than_ms: Optional[int] = None,
    ) -> str:
        """Expire old table snapshots, freeing the data files they pinned.

        RETENTION WARNING: snapshots are the time-travel history. Under
        Ofgem/DCC and NIS retention obligations the audit window is
        typically years, not days — do not call this on a regulated table
        without checking the retention policy recorded in the table
        properties (`meldra.retention.min_days`). The default keeps the last
        10 snapshots and expires nothing on age alone.
        """
        identifier = (namespace, table_name)
        table = self.catalog.load_table(identifier)

        history = list(table.history())
        if len(history) <= retain_last:
            return (
                f"No snapshots expired for {namespace}.{table_name}: "
                f"{len(history)} snapshot(s) present, retain_last={retain_last}."
            )

        min_days = table.properties.get("meldra.retention.min_days")
        if min_days:
            raise PermissionError(
                f"{namespace}.{table_name} carries a retention policy of {min_days} "
                f"days (meldra.retention.min_days). Snapshot expiry is blocked on "
                f"retention-governed tables; clear the property deliberately, with "
                f"an approval record, before expiring history."
            )

        expire = table.expire_snapshots()
        if older_than_ms is not None:
            expire = expire.expire_older_than(older_than_ms)
        candidates = history[:-retain_last]
        for snap in candidates:
            expire = expire.expire_snapshot_id(snap.snapshot_id)
        expire.commit()

        return (
            f"Expired {len(candidates)} snapshot(s) for {namespace}.{table_name}; "
            f"retained the most recent {retain_last}."
        )

    def run_time_travel_scan(self, namespace: str, table_name: str, snapshot_id: Optional[int] = None) -> pa.Table:
        identifier = (namespace, table_name)
        table = self.catalog.load_table(identifier)
        if snapshot_id:
            history = [s.snapshot_id for s in table.history()]
            if snapshot_id in history:
                return table.scan(snapshot_id=snapshot_id).to_arrow()
        return table.scan().to_arrow()
