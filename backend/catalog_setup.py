import os
from pyiceberg.catalog import load_catalog
from pyiceberg.catalog.sql import SqlCatalog

def get_catalog():
    """
    Initializes and returns an Iceberg catalog.
    If AWS environment variables are set, it uses AWS Glue and S3.
    Otherwise, it defaults to a local SQLite catalog.
    """
    catalog_name = "default"
    
    # Check if we are running in the cloud (e.g. AWS App Runner)
    s3_uri = os.environ.get("S3_WAREHOUSE_URI")
    aws_region = os.environ.get("AWS_REGION", "eu-west-2")
    
    if s3_uri:
        print(f"Connecting to AWS Glue Catalog in {aws_region} with S3 warehouse: {s3_uri}")
        catalog = load_catalog(
            catalog_name,
            **{
                "type": "glue",
                "s3.region": aws_region,
                "warehouse": s3_uri
            }
        )
        return catalog
    else:
        # Local fallback for testing
        print("Connecting to Local SQLite Catalog.")
        warehouse_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warehouse")
        os.makedirs(warehouse_path, exist_ok=True)
        catalog = load_catalog(
            catalog_name,
            **{
                "uri": f"sqlite:///{warehouse_path}/iceberg_catalog.db",
                "warehouse": f"file://{warehouse_path}",
            }
        )
        return catalog

def create_namespace_if_not_exists(catalog: SqlCatalog, namespace: str):
    """
    Creates a namespace in the catalog if it does not already exist.
    """
    try:
        catalog.create_namespace(namespace)
        print(f"Namespace '{namespace}' created.")
    except Exception as e:
        if "already exists" in str(e).lower() or "NamespaceAlreadyExistsError" in type(e).__name__:
            print(f"Namespace '{namespace}' already exists.")
        else:
            raise e

if __name__ == "__main__":
    cat = get_catalog()
    create_namespace_if_not_exists(cat, "default")
    print("Catalog initialized.")
