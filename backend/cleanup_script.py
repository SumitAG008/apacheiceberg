import os
import boto3
import time
from pyiceberg.catalog import load_catalog

def cleanup_demo_namespaces(max_age_hours=1):
    """
    Finds and deletes any Iceberg namespaces (and their tables) 
    that start with 'demo_' and are older than max_age_hours.
    """
    print(f"Starting cleanup of demo namespaces older than {max_age_hours} hour(s)...")
    
    # Initialize catalog
    try:
        catalog = load_catalog(
            "default",
            **{
                "type": "glue",
                "s3.region": os.environ.get("AWS_REGION", "eu-west-2")
            }
        )
    except Exception as e:
        print(f"Failed to load catalog: {e}")
        return

    # Initialize Glue client to check creation time
    glue_client = boto3.client('glue', region_name=os.environ.get("AWS_REGION", "eu-west-2"))
    
    # Get all namespaces (databases in Glue)
    namespaces = catalog.list_namespaces()
    current_time = time.time()
    
    deleted_count = 0
    
    for ns_tuple in namespaces:
        ns_name = ns_tuple[0]
        
        # Only target demo namespaces
        if not ns_name.startswith("demo_"):
            continue
            
        try:
            # Check age using AWS Glue API
            db = glue_client.get_database(Name=ns_name)
            create_time = db['Database']['CreateTime'].timestamp()
            age_hours = (current_time - create_time) / 3600
            
            if age_hours > max_age_hours:
                print(f"Found old namespace: {ns_name} ({age_hours:.1f} hours old)")
                
                # Must drop all tables before dropping namespace
                tables = catalog.list_tables(ns_tuple)
                for table_identifier in tables:
                    print(f"  Dropping table: {table_identifier[1]}")
                    try:
                        catalog.drop_table(table_identifier)
                    except Exception as e:
                        print(f"  Failed to drop table {table_identifier[1]}: {e}")
                
                # Drop the namespace
                print(f"  Dropping namespace: {ns_name}")
                try:
                    catalog.drop_namespace(ns_tuple)
                    deleted_count += 1
                except Exception as e:
                    print(f"  Failed to drop namespace {ns_name}: {e}")
                    
        except Exception as e:
            print(f"Error processing namespace {ns_name}: {e}")
            
    print(f"Cleanup complete. Deleted {deleted_count} old demo namespaces.")

if __name__ == "__main__":
    # Ensure AWS credentials exist
    if not all(k in os.environ for k in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]):
        print("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")
    else:
        # Run cleanup
        cleanup_demo_namespaces(max_age_hours=1)
