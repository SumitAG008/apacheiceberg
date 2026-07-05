import json
from typing import Dict, Any, List, Optional
from catalog_setup import get_catalog

class MeldraPipeline:
    def __init__(self, namespace: str = "default"):
        self.catalog = get_catalog()
        self.namespace = namespace

    def set_table_layer(self, table_name: str, layer: str) -> None:
        """
        Sets the medallion layer property (bronze, silver, gold) of an Iceberg table.
        """
        if layer.lower() not in ["bronze", "silver", "gold"]:
            raise ValueError("Medallion layer must be one of: bronze, silver, gold")
            
        identifier = (self.namespace, table_name)
        table = self.catalog.load_table(identifier)
        table.transaction().set_properties({"layer": layer.lower()}).commit()

    def get_pipeline_dag_status(self) -> List[Dict[str, Any]]:
        """
        Returns a list of stages and tables showing pipeline status.
        Matches the visual orchestrator layout.
        """
        # Automatically classify tables in namespace by layer tag
        tables = self.catalog.list_tables(self.namespace)
        
        stages = [
            {"id": "bronze", "name": "Bronze Ingest (Raw)", "tables": [], "status": "healthy"},
            {"id": "silver", "name": "Silver Deduplication (Clean)", "tables": [], "status": "healthy"},
            {"id": "gold", "name": "Gold Consolidation (BI)", "tables": [], "status": "healthy"}
        ]
        
        for tbl in tables:
            tbl_name = tbl[1] if len(tbl) > 1 else tbl[0]
            try:
                table = self.catalog.load_table(tbl)
                layer = table.properties.get("layer", "bronze").lower()
                
                # Check for active validation rules count
                rules_str = table.properties.get("data_contracts", "[]")
                rules_count = len(json.loads(rules_str))
                
                table_info = {
                    "name": tbl_name,
                    "rows": len(table.scan().to_arrow()),
                    "contracts_count": rules_count
                }
                
                if layer == "bronze":
                    stages[0]["tables"].append(table_info)
                elif layer == "silver" or "silver" in tbl_name or "clean" in tbl_name:
                    stages[1]["tables"].append(table_info)
                else:
                    stages[2]["tables"].append(table_info)
            except Exception:
                pass
                
        return stages
